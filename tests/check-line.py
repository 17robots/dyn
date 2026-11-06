#!/usr/bin/env python3
"""Debug builds name the source line of a failed runtime check."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-check-line-') as temporary:
    program = Path(temporary) / 'program'
    subprocess.run([DYN, 'build', str(ROOT / 'tests/check-line'), '--debug', '--quiet', '--no-cache',
                    '--output', str(program)], check=True, timeout=120)
    result = subprocess.run([str(program)], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert 'in divide at ' in result.stderr and 'main.dyn:3\n' in result.stderr, result.stderr
print('PASS failed checks report their line')
