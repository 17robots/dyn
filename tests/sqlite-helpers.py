#!/usr/bin/env python3
"""vendor/sqlite statement cache, run, first, query/next, column readers,
constraint detection, open_schema and transaction (debug/release)."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = '''cached once true
duplicate false constraint true
first 3 cy 2
missing false
row cy 20
row di 30
row ed 40
total 90 bad sql true
transaction true stored true true false rows 2
bad schema true
'''
with tempfile.TemporaryDirectory(prefix='dyn-sqlite-helpers-') as temporary:
    for mode in ('--debug', '--release'):
        program = Path(temporary) / 'helpers'
        subprocess.run([DYN, 'build', str(ROOT / 'tests/sqlite-helpers'), mode, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=180, env={**os.environ, 'DYN_SDK': str(ROOT)})
        database = Path(temporary) / f'items{mode}.sqlite3'
        output = subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30,
                                env={**os.environ, 'SQLITE_HELPERS_DB': str(database)}).stdout
        assert output == EXPECTED, output
print('sqlite helpers ok')
