#!/usr/bin/env python3
"""Live range splitting around loops: two loops hot on different values,
values live through a loop unused in it, floats, breaks and empty loops
give the same results at every level and on every 64-bit target."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = '30600261\n1336049385 881\n800270506 1400490878 134\n18708470 1750\n9538963\n'
with tempfile.TemporaryDirectory(prefix='dyn-loop-split-') as temporary:
    for name, flags, emulator in (('debug', ['--debug'], []), ('release', ['--release'], []),
                                  ('o3', ['--release', '--opt-level', '3'], []),
                                  ('arm', ['--target', 'aarch64-linux', '--release', '--opt-level', '3'], ['qemu-aarch64']),
                                  ('riscv', ['--target', 'riscv64-linux', '--release', '--opt-level', '3'], ['qemu-riscv64'])):
        program = Path(temporary) / name
        subprocess.run([DYN, 'build', str(ROOT / 'tests/loop-register-split'), *flags, '--quiet',
                        '--no-cache', '--output', str(program)], check=True, timeout=120)
        if emulator and not shutil.which(emulator[0]):
            continue
        result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == EXPECTED, (name, result)
print('PASS loop register splitting')
