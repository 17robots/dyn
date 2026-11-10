#!/usr/bin/env python3
"""Branches threaded past boolean phis: short-circuit loops and a flag set
by break, where a phi keeps a single incoming value afterwards."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = 'false\nfalse\nfalse\ntrue\ntrue\ntrue\nfalse\n'
with tempfile.TemporaryDirectory(prefix='dyn-bool-phi-') as temporary:
    for name, flags, emulator in (('debug', ['--debug'], []), ('release', ['--release'], []),
                                  ('o3', ['--release', '--opt-level', '3'], []),
                                  ('arm', ['--target', 'aarch64-linux', '--release'], ['qemu-aarch64'])):
        program = Path(temporary) / name
        subprocess.run([DYN, 'build', str(ROOT / 'tests/bool-phi-threading'), *flags, '--quiet',
                        '--no-cache', '--output', str(program)], check=True, timeout=120)
        if emulator and not shutil.which(emulator[0]):
            continue
        result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == EXPECTED, (name, result)
print('PASS boolean phi threading')
