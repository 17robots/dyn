#!/usr/bin/env python3
"""Vectorized slice sums match scalar results at every length and width."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-slice-sum-') as temporary:
    root = Path(temporary)
    for name, flags in (('debug', ['--debug']), ('release', ['--release']), ('vector', ['--release', '--opt-level', '3', '--opt-remarks'])):
        program = root / name
        run = subprocess.run([DYN, 'build', str(ROOT / 'tests/slice-sum'), *flags, '--no-cache', '--quiet',
                              '--output', str(program)], capture_output=True, text=True, timeout=120)
        assert run.returncode == 0, run.stdout + run.stderr
        if name == 'vector':
            assert 'vectorized slice sum' in run.stdout + run.stderr, run.stdout + run.stderr
        subprocess.run([str(program)], check=True, timeout=30)
print('PASS slice sums')
