#!/usr/bin/env python3
"""std/terminal and std/dynlib on every desktop kernel.

Cross-builds both fixtures for Linux, macOS and Windows. Runs Linux natively
(the terminal fixture also inside a 37x91 pseudo-terminal) and Windows under
wine when it is installed.
"""
import fcntl
import os
from pathlib import Path
import pty
import shutil
import struct
import subprocess
import sys
import tempfile
import termios

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
FIXTURES = ROOT / 'tests/platform-parity'
TARGETS = ['x86_64-linux', 'aarch64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows']


def build(name, target, output):
    subprocess.run([str(DYN), 'build', str(FIXTURES / name), '--target', target, '--output', str(output)], check=True, timeout=300)


def run_in_pty(program):
    pid, master = pty.fork()
    if pid == 0:
        os.execv(str(program), [str(program)])
    fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack('HHHH', 37, 91, 0, 0))
    output = b''
    while True:
        try:
            chunk = os.read(master, 4096)
        except OSError:
            break
        if not chunk:
            break
        output += chunk
    _, status = os.waitpid(pid, 0)
    if os.waitstatus_to_exitcode(status) != 0:
        raise SystemExit('terminal fixture failed in a pseudo-terminal: ' + output.decode(errors='replace'))


with tempfile.TemporaryDirectory(prefix='dyn-platform-parity-') as directory:
    work = Path(directory)
    for name in ['dynlib', 'terminal']:
        for target in TARGETS:
            # Linking libc for another Linux architecture needs its sysroot.
            if name == 'dynlib' and target == 'aarch64-linux':
                continue
            build(name, target, work / f'{name}-{target}')
        if sys.platform == 'linux' and os.uname().machine == 'x86_64':
            subprocess.run([str(work / f'{name}-x86_64-linux')], stdin=subprocess.DEVNULL, check=True, timeout=60)
        if shutil.which('wine'):
            subprocess.run(['wine', str(work / f'{name}-x86_64-windows')], stdin=subprocess.DEVNULL, check=True, timeout=120)
    if sys.platform == 'linux' and os.uname().machine == 'x86_64':
        run_in_pty(work / 'terminal-x86_64-linux')
print('platform parity: ok')
