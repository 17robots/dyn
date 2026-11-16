#!/usr/bin/env python3
"""HPACK decoding against 300 blocks from Go's encoder (dynamic table
evictions, size updates, Huffman, never-indexed fields) and encode/decode
round trips, and the same fields through QPACK (static table only).
tools/hpack-vectors regenerates the vectors."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-hpack-') as temporary:
    program = Path(temporary) / 'hpack'
    for mode in ('--debug', '--release'):
        subprocess.run([DYN, 'build', str(ROOT / 'tests/hpack'), mode, '--quiet', '--no-cache', '--output', str(program)],
                       check=True, timeout=180)
        output = subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30).stdout
        assert output == 'decoded 300 encoded 300 size 4030\n', output
print('hpack ok')
