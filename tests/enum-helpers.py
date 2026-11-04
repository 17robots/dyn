#!/usr/bin/env python3
"""std/enums, zero-result division, saturating casts and try_append (debug/release)."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-enum-helpers-') as temporary:
    for mode in ('--debug', '--release'):
        program = Path(temporary) / ('program' + mode)
        subprocess.run([DYN, 'build', str(ROOT / 'tests/enum-helpers'), mode, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=120)
        subprocess.run([str(program)], check=True, timeout=30)
print('PASS enums, or_zero division, saturating casts and try_append (debug/release)')
