#!/usr/bin/env python3
"""An element address through a phi skips its pointer checks only when every
incoming value is one: a phi that may be nil still traps on access."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-element-phi-') as temporary:
    for name, flags, emulator in (('debug', ['--debug'], []), ('release', ['--release', '--opt-level', '3'], []),
                                  ('arm', ['--target', 'aarch64-linux', '--release'], ['qemu-aarch64'])):
        program = Path(temporary) / name
        subprocess.run([DYN, 'build', str(ROOT / 'tests/element-address-phi'), *flags, '--quiet',
                        '--no-cache', '--output', str(program)], check=True, timeout=120)
        if emulator and not shutil.which(emulator[0]):
            continue
        result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode != 0 and result.stdout == '3\n' and 'pointer.nonnull' in result.stderr, (name, result)
print('PASS element address phis')
