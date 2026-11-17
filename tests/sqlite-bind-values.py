#!/usr/bin/env python3
"""vendor/sqlite bind_values binds integers, text, Blob, floats and Null to
parameters in order, rejects unsupported types, and done resets a statement."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-sqlite-bind-') as temporary:
    for mode in ('--debug', '--release'):
        program = Path(temporary) / 'bind'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/sqlite-bind-values'), mode, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=180, env={**os.environ, 'DYN_SDK': str(ROOT)})
        output = subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30).stdout
        assert output == 'bind Ok\nstep Done\nbad InvalidInput\n42 text 2 1.5 1\n', output
print('sqlite bind values ok')
