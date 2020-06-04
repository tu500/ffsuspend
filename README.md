FFSuspend
=========

A small script to monitor processes and i3 events in order to `SIGSTOP` GUI
processes when their X windows are not on a visible i3 workspace.

But WHY?!
---------

I'm travelling a lot by train and use that time to work on stuff on my laptop.
I tend to keep open some programs, like a browser with some documentation or
library reference. However some programs, after being used for a while, tend to
consume up to one CPU core just for idling (looking at you, firefox), which
significantly lowers battery life and brings me in the uncomfortable situation
to have a constantly warm computer on my lap. So instead of tackling the root
cause, I went for the easiest route and this script is the result of that.

Dependencies
------------

This is a hacky script that defers much of its functions by parsing the output
of some utility programs. These need to be installed for it to work:

* i3-msg
* killall
* ps
* xdotool
* xsel

Caveats / Disclaimer
--------------------

The X clipboard protocol is an IPC protocol that talks to the current owner of
the clipboard, whenever its contents is requested. If this process is
`SIGSTOP`ed, applications tend to freeze indefinitely, whenever trying to read
the clipboard contents.

While there is probably a cleaner solution, FFSuspend has a hacky feature that
monitors clipboard contents and skips one cycle of stopping a process, when the
clipboard was changed while that process' window was visible. This can be
enabled with the `-c` commandline flag.

There may be other 'interesting' sideeffects when `SIGSTOP`ing processes, so be
wary and use at your own risk.

License
-------

FFSuspend is licensed under the GPLv3 or later, see `LICENSE.txt`.
