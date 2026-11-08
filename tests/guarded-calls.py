#!/usr/bin/env python3
"""Calls through stored functions: a lone candidate is inlined behind a guard."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-guarded-calls-') as temporary:
    for case in ('one', 'two'):
        for name, flags, emulator in (('debug', ['--debug'], []), ('release', ['--release', '--opt-level', '3'], []),
                                      ('arm', ['--target', 'aarch64-linux', '--release'], ['qemu-aarch64'])):
            program = Path(temporary) / (case + name)
            subprocess.run([DYN, 'build', str(ROOT / 'tests/guarded-calls' / case), *flags, '--quiet',
                            '--no-cache', '--output', str(program)], check=True, timeout=120)
            if not emulator or shutil.which(emulator[0]):
                subprocess.run([*emulator, str(program)], check=True, timeout=60)
    # With one candidate, the release loop compares against double and has
    # double's multiply inline; the indirect call is only the fallback.
    listing = subprocess.run(['objdump', '-d', '--no-show-raw-insn', str(Path(temporary) / 'onerelease')],
                             capture_output=True, text=True, check=True).stdout
    body = next(block for block in listing.split('\n\n') if '<main>:' in block or '_run>:' in block.split('\n', 1)[0])
    assert 'call   *' in body and ('add    %r' in body or 'lea' in body), body
print('PASS guarded calls')
