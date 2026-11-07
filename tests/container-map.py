#!/usr/bin/env python3
"""std/container/map behaves the same in debug, release and on AArch64."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-container-map-') as temporary:
    for name, flags, emulator in (('debug', ['--debug'], []), ('release', ['--release', '--opt-level', '3'], []),
                                  ('arm', ['--target', 'aarch64-linux', '--release'], ['qemu-aarch64'])):
        program = Path(temporary) / name
        subprocess.run([DYN, 'build', str(ROOT / 'tests/container-map'), *flags, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=120)
        if not emulator or shutil.which(emulator[0]):
            subprocess.run([*emulator, str(program)], check=True, timeout=60)
print('PASS container map')
