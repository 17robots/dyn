#!/usr/bin/env python3
"""Bare `{ ... }` blocks: defers run at the closing brace, locals end there,
and a block that returns ends the function. Debug, release and O3 agree."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = '''start
inside
block cleanup
after block
1
3
inner
3
loop 0
loop 1
10
deferred block
'''
with tempfile.TemporaryDirectory(prefix='dyn-bare-block-') as temporary:
    program = Path(temporary) / 'program'
    for flags in (['--debug'], ['--release'], ['--release', '--opt-level', '3']):
        subprocess.run([DYN, 'build', str(ROOT / 'tests/bare-block'), *flags, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=180)
        result = subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30).stdout
        assert result == EXPECTED, (flags, result)
print('bare block ok')
