#!/usr/bin/env python3
"""Debug builds name a failed check's line, and one type error reports once."""
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
    source = Path(temporary) / 'cascade'
    source.mkdir()
    (source / 'main.dyn').write_text('fn main() {\n  h: u64 = 1\n  b: u8 = 2\n  h = (h ^ b) * 1099511628211\n}\n')
    result = subprocess.run([DYN, 'check', str(source)], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'mismatched types' in result.stderr, result.stderr
    assert result.stderr.count('error:') == 1, result.stderr
print('PASS failed checks report their line; one error reports once')
