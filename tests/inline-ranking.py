#!/usr/bin/env python3
"""Ranked inlining: a small call in a loop is inlined, a large one behind a
rare branch stays a call, and `_ = f()` of an inlined void call still runs."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = '100000 102 4266731690\n'
with tempfile.TemporaryDirectory(prefix='dyn-inline-ranking-') as temporary:
    for name, flags, emulator in (('debug', ['--debug'], []), ('o3', ['--release', '--opt-level', '3'], []),
                                  ('arm', ['--target', 'aarch64-linux', '--release', '--opt-level', '3'], ['qemu-aarch64'])):
        program = Path(temporary) / name
        subprocess.run([DYN, 'build', str(ROOT / 'tests/inline-ranking'), *flags, '--quiet',
                        '--no-cache', '--output', str(program)], check=True, timeout=120)
        if emulator and not shutil.which(emulator[0]):
            continue
        result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == EXPECTED, (name, result)
    if platform.machine().lower() in ('x86_64', 'amd64') and shutil.which('objdump'):
        listing = subprocess.run(['objdump', '-d', '--no-show-raw-insn', str(Path(temporary) / 'o3')],
                                 capture_output=True, text=True, check=True).stdout
        body = next(block for block in listing.split('\n\n') if '<main>:' in block)
        assert '<rebuild>' in body, body
        assert '<bump>' not in body and '<note>' not in body, body
print('PASS inline ranking')
