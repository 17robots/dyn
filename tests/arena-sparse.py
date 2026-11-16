#!/usr/bin/env python3
"""mem.advise_sparse keeps transparent huge pages off a sparsely touched
region: 32 scattered one-byte writes stay well under 1 MiB resident, where
huge pages would make them 64 MiB. Meaningful only with THP set to always."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
setting = Path('/sys/kernel/mm/transparent_hugepage/enabled')
if sys.platform != 'linux' or not setting.exists() or '[always]' not in setting.read_text():
    print('SKIP arena sparse: needs Linux with transparent huge pages set to always')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-arena-sparse-') as temporary:
    program = Path(temporary) / 'sparse'
    for mode in ('--debug', '--release'):
        subprocess.run([DYN, 'build', str(ROOT / 'tests/arena-sparse'), mode, '--quiet', '--no-cache', '--output', str(program)],
                       check=True, timeout=180)
        grown = int(subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30).stdout)
        assert grown < 1024, f'{grown} KiB resident after 32 one-byte writes'
print('PASS arena sparse: advised regions take 4 KiB pages')
