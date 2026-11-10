#!/usr/bin/env python3
"""parse.u64_decimal and parse.i64_decimal: limits, overflow, syntax offsets."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
for mode in ([], ['--release']):
    result = subprocess.run([DYN, 'run', str(ROOT / 'tests/parse-integers'), '--quiet', '--no-cache'] + mode,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0 and result.stdout == 'ok\n', result
print('PASS parse integers (debug/release)')
