import os
from setuptools import setup

def read(fname):
    return open(os.path.join(os.path.dirname(__file__), fname)).read()

setup(
    name = 'ffsuspend',
    version = '0.1',
    author = 'Philip Matura',
    author_email = 'philip.m@tura-home.de',
    description = ('Suspend processes when X window not visible (i3-wm only)'),
    py_modules=['ffsuspend'],
    long_description=read('README.md'),
    long_description_content_type='text/markdown',
    url='https://github.com/tu500/ffsuspend',
    license='GPLv3+',
    entry_points='''
        [console_scripts]
        ffsuspend=ffsuspend:main
    ''',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Programming Language :: Python :: 3',
        'Environment :: X11 Applications',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Operating System :: POSIX :: Linux',
        'Topic :: Desktop Environment :: Window Managers',
        'Typing :: Typed',
    ],
)
