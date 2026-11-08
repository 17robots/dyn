#!/usr/bin/env python3
"""Loop counter replacement after strength reduction: ranges that start
past their end, a break before the bound, and a scaled bound that would
wrap, which keeps the original counter."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = '138 0 0 30 3\n11529215046068469805\n'
with tempfile.TemporaryDirectory(prefix='dyn-loop-counter-') as temporary:
    for name, flags, emulator in (('debug', ['--debug'], []), ('release', ['--release'], []),
                                  ('o3', ['--release', '--opt-level', '3'], []),
                                  ('arm', ['--target', 'aarch64-linux', '--release'], ['qemu-aarch64'])):
        program = Path(temporary) / name
        subprocess.run([DYN, 'build', str(ROOT / 'tests/loop-counter-replacement'), *flags, '--quiet',
                        '--no-cache', '--output', str(program)], check=True, timeout=120)
        if emulator and not shutil.which(emulator[0]):
            continue
        result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == EXPECTED, (name, result)
print('PASS loop counter replacement')
