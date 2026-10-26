#!/usr/bin/env python3
"""distinct, packed and is are contextual: ordinary names outside their constructs."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-contextual-keywords-') as temporary:
    for release in (False, True):
        program = Path(temporary) / f'program-{release}'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/contextual-keywords'), '--quiet', '--no-cache',
                        '--output', str(program)] + (['--release'] if release else []), check=True, timeout=120)
        result = subprocess.run([str(program)], capture_output=True, text=True, timeout=30)
        assert result.returncode == 0 and result.stdout == 'ok\n', result
    formatted = subprocess.run([DYN, 'fmt', '--check', str(ROOT / 'tests/contextual-keywords')],
                               capture_output=True, text=True, timeout=60)
    assert formatted.returncode == 0, formatted
print('PASS contextual keywords: distinct, packed and is as names, types and patterns (debug/release)')
