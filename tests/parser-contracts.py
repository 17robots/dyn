#!/usr/bin/env python3
"""Bounded UTF-8/capacity and fragmented CSV/XML parser contracts."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-parser-contracts-') as temporary:
    for release in (False, True):
        output = Path(temporary) / ('program.exe' if os.name == 'nt' else 'program')
        subprocess.run([DYN, 'build', str(ROOT / 'tests/parser-contracts'),
                        '--no-cache', '--quiet', '--output', str(output)] +
                       (['--release'] if release else []), check=True, timeout=90)
        subprocess.run([str(output)], check=True, timeout=15)
print('PASS JSON UTF-8/capacity rollback and CSV/XML fragmentation (debug/release)')
