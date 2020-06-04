#!/usr/bin/python3
#
# FFSuspend
# Copyright (C) 2020  Philip Matura
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import argparse
import enum
import json
import logging
import os
import subprocess
import sys

from typing import List, Generator, Dict, Any, Optional, Set, Iterable

def execute_iter_lines(cmd: List[str]) -> Generator[str, None, None]:
    """
    Start a subprocess and blockingly yield its stdout line-by-line.

    `cmd` is the first parameter passed to subprocess.Popen
    """

    popen = subprocess.Popen(cmd, stdout=subprocess.PIPE, universal_newlines=True)
    for stdout_line in iter(popen.stdout.readline, ''):
        yield stdout_line
    popen.stdout.close()
    return_code = popen.wait()
    if return_code:
        raise subprocess.CalledProcessError(return_code, cmd)

def get_clipboard() -> Optional[bytes]:
    """
    Try to read the X clipboard. Returns None if reading timed out. The timeout
    is 100ms.
    """

    try:
        p = subprocess.run(['xsel', '-b'], stderr=subprocess.STDOUT, stdout=subprocess.PIPE, timeout=0.1)
        return p.stdout
    except subprocess.TimeoutExpired:
        return None

def get_process_ids(process_name: str) -> Set[int]:
    """
    Returns a list of PIDs for a given binary name.
    """

    ps_list = subprocess.check_output(['ps', 'ax'])

    res = set()

    for line in ps_list.splitlines()[1:]:
        pid, _, _, _, *command = line.split()
        if command[0] == process_name.encode() or command[0].endswith(f'/{process_name}'.encode()):
            res.add(int(pid.decode()))

    return res

def get_xwindows_for_pid(pid: int) -> Set[int]:
    """
    Returns all X window IDs corresponding to a process given by its PID.
    """
    try:
        xwid_list = subprocess.check_output(['xdotool', 'search', '--pid', str(pid)])
        return {int(s) for s in xwid_list.splitlines()}
    except subprocess.CalledProcessError:
        return set()

def get_workspaces_for_xwindows(xwid_list: Iterable[int], tree: Any = None) -> Set[str]:
    """
    Returns all i3 workspaces (by name) that contain an X window from
    `xwid_list` (given by its X window ID).

    The i3 object tree (as obtained from `i3-msg -t get_workspaces`) may be
    given with the`tree` argument, in which case it will not be queried from
    i3.
    """

    def check_workspace_tree(nodes):
        """
        Recursively check whether any node in an i3-tree is a window with a
        window-id contained in the xwid_list.
        """
        for node in nodes:
            if node['window'] in xwid_list:
                return True
            elif check_workspace_tree(node['nodes']):
                return True
        return False

    workspaces = set()

    if tree is None:
        tree = json.loads(subprocess.check_output(['i3-msg', '-t', 'get_tree']))

    assert tree['type'] == 'root'
    for output in tree['nodes']:
        assert output['type'] == 'output'
        for container in output['nodes']:
            assert container['type'] in ('con', 'dockarea')
            if container['type'] == 'con':
                for workspace in container['nodes']:
                    assert workspace['type'] == 'workspace'

                    if check_workspace_tree(workspace['nodes']):
                        workspaces.add(workspace['name'])

    return workspaces

def get_workspaces_for_process(process_name: str, tree: Any = None) -> Set[str]:
    """
    Returns all i3 workspaces (by name) that contain an X window owned by a
    process with binary name `process_name`.

    The `tree` argument is the same as in `get_workspaces_for_xwindows`.
    """
    pids = get_process_ids(process_name)
    xwids = set.union(*(get_xwindows_for_pid(pid) for pid in pids))
    return get_workspaces_for_xwindows(xwids, tree)


class StoppedState(enum.Enum):
    STOPPED = 0
    RUNNING = 1

class ProcessManager():

    process_name: str
    inhibit: bool
    manager: 'Manager'
    state: StoppedState
    monitored_workspaces: Set[str]
    pid_list: Set[int]
    xwid_list: Set[int]
    logger: 'logging.Logger'

    def __init__(self, process_name: str, manager: 'Manager') -> None:
        self.process_name = process_name
        self.manager = manager
        self.inhibit = False
        self.state = StoppedState.RUNNING

        self.pid_list = set()
        self.xwid_list = set()
        self.monitored_workspaces = set()

        self.logger = logging.getLogger(process_name)

    def update_workspace_list(self, moved_only: bool = False, tree: Any = None) -> None:
        """
        Update monitored workspaces to those containing a window owned by a
        process with the configured process name.

        If `moved_only` is True, will not scan for new processes or X windows,
        assuming only that a window might have been moved to a different
        workspace.

        The `tree` argument is the same as in `get_workspaces_for_xwindows`.
        """

        self.logger.debug('updating workspace list')

        update_workspaces = moved_only

        if not moved_only:
            # no new windows, no need to check for new PIDs or XWindow IDs
            pids = get_process_ids(self.process_name)
            if pids != self.pid_list:
                self.logger.debug(f'new pids: {pids}')
                self.pid_list = pids

            if len(pids) == 0:
                return

            xwids = set.union(*(get_xwindows_for_pid(pid) for pid in pids))
            if xwids != self.xwid_list:
                self.logger.debug(f'new xwindow ids: {xwids}')
                self.xwid_list = xwids
                update_workspaces = True

        if update_workspaces:
            mws = get_workspaces_for_xwindows(xwids, tree)
            if mws != self.monitored_workspaces:
                self.logger.debug(f'new workspace list: {mws}')
                self.monitored_workspaces = mws

    def get_target_state(self) -> StoppedState:
        """
        Return the current target state, by checking whether a monitored
        workspace is visible on any output.
        """

        for name in self.monitored_workspaces:
            if name in self.manager.workspace_by_output.values():
                return StoppedState.RUNNING
        return StoppedState.STOPPED

    def send_stop(self) -> None:
        """SIGSTOP controlled processes"""
        try:
            self.logger.info('stopping')
            subprocess.check_output(['killall', '-SIGSTOP', '-g', self.process_name], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            pass
        self.state = StoppedState.STOPPED

    def send_cont(self) -> None:
        """SIGCONT controlled processes"""
        try:
            self.logger.info('continuing')
            subprocess.check_output(['killall', '-SIGCONT', '-g', self.process_name], stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            pass
        self.state = StoppedState.RUNNING

    def inhibit_if_visible(self) -> None:
        """
        If associated workspaces are visible, inhibit process stopping until
        next continue request
        """

        if self.get_target_state() == StoppedState.RUNNING:
            self.logger.info('inhibiting')
            self.inhibit = True

    def check_state(self) -> None:
        """
        Update process state to current target state
        """

        target_state = self.get_target_state()

        if target_state == StoppedState.STOPPED and self.state == StoppedState.RUNNING:

            if not self.inhibit:
                self.send_stop()

            else:
                self.logger.debug('not stopping, inhibited')

        elif target_state == StoppedState.RUNNING:

            if self.inhibit:
                self.inhibit = False

            if self.state == StoppedState.STOPPED:
                self.send_cont()

class Manager():

    workspace_by_output: Dict[str, str]
    last_clip: Optional[bytes]
    monitored_processes: List[ProcessManager]
    enable_clibboard_checking: bool

    def __init__(self, args: argparse.Namespace) -> None:
        self.workspace_by_output = {}
        self.last_clip = None
        self.enable_clibboard_checking = args.check_clipboard

        self.monitored_processes = [
                ProcessManager(process_name, self) for process_name in args.processes
            ]

        for mp in self.monitored_processes:
            mp.update_workspace_list()

    def update_visible_workspaces(self) -> None:
        """
        Update `self.workspace_by_output` from an i3 object tree.
        """

        s = subprocess.check_output(['i3-msg', '-t', 'get_workspaces'])
        j = json.loads(s)

        d = {}
        for i in j:
            if i['visible']:
                d[i['output']] = i['name']

        self.workspace_by_output = d

    def update_from_focus_event(self, j) -> None:
        """
        Update `self.workspace_by_output` from an i3 focus workspace event object.
        """

        current_name = j['current']['name']
        current_output = j['current']['output']
        self.workspace_by_output[current_output] = current_name

    def check_clipboard(self) -> bool:
        """
        Returns True if the clipboard has been changed since the last call.
        """

        c = get_clipboard()
        b = bool(c is not None and c != self.last_clip)
        if c is not None:
            self.last_clip = c
        return b

    def run(self) -> None:
        try:
            if self.enable_clibboard_checking:
                self.last_clip = get_clipboard()
            self.update_visible_workspaces()

            for mp in self.monitored_processes:
                mp.check_state()

            for line in execute_iter_lines(['i3-msg', '-t', 'subscribe', '-m', '[ "window", "workspace" ]']):
                j = json.loads(line)

                assert 'change' in j

                if 'current' in j:
                    # workspace event

                    # j['change']: init, empty, move, focus

                    # TODO: need to handle workspace move event?

                    if j['change'] == 'focus':

                        # check before updating focussed workspace
                        if self.enable_clibboard_checking and self.check_clipboard():
                            logging.debug('clipboard changed')
                            for mp in self.monitored_processes:
                                mp.inhibit_if_visible()

                        self.update_from_focus_event(j)

                        for mp in self.monitored_processes:
                            mp.check_state()

                elif 'container' in j:
                    # window event

                    # j['change']: new, focus, move, title, close

                    if j['change'] in ('new', 'close'):
                        for mp in self.monitored_processes:
                            mp.update_workspace_list()
                            mp.check_state()

                    if j['change'] == 'move':
                        for mp in self.monitored_processes:
                            mp.update_workspace_list(moved_only=True)
                            mp.check_state()

                else:
                    assert False

        finally:
            logging.info('continuing all processes')
            for mp in self.monitored_processes:
                mp.send_cont()

def configure_logging(logging_type, loglevel, logfile):

    numeric_level = getattr(logging, loglevel.upper(), None)

    if not isinstance(numeric_level, int):
        raise ValueError('Invalid log level: %s' % loglevel)

    if logging_type == 'stdout':
        logging.basicConfig(
                format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                level=numeric_level
            )
    elif logging_type == 'file':
        assert logfile is not None
        logging.basicConfig(
                filename=logfile,
                format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
                level=numeric_level
            )
    elif logging_type == 'journald':
        try:
            from systemd.journal import JournalHandler
        except ImportError:
            print('Journald logging format needs the systemd-python package. Try installing with "pip install systemd-python".')
            sys.exit(1)
        logging.basicConfig(
                handlers=[JournalHandler()],
                format='%(name)s: %(message)s',
                level=numeric_level
            )
    else:
        assert False

def main() -> None:
    parser = argparse.ArgumentParser(
            description='FFSuspend'
        )

    parser.add_argument('processes', nargs='+', help='Processes to monitor')
    parser.add_argument('-c', '--check-clipboard', action='store_true', help='Check X clipboard when changing workspaces, skip stopping processes if changed')
    parser.add_argument('-p', '--pid-file', help='Write own PID to given file')

    logging_group = parser.add_argument_group('Logging')
    logging_group.add_argument('--logging-type', default='stdout', choices=['stdout', 'file', 'journald'])
    logging_group.add_argument('--logfile', help='Only used for logging-type=file')
    logging_group.add_argument('--loglevel', default='debug', help='Standard python logging levels error,warning,info,debug')

    args = parser.parse_args()

    configure_logging(args.logging_type, args.loglevel, args.logfile)

    if args.pid_file:
        with open(args.pid_file, 'w') as f:
            f.write(str(os.getpid()))

    m = Manager(args)
    m.run()

if __name__ == "__main__":
    main()
