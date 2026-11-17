#!/usr/bin/env python3
"""std/compress/gzip encoder: every level round-trips through Python's gzip on
text, JSON, source code, a binary, random and degenerate inputs, and output
stays within 2% of zlib at the same level (levels 4-9; 1-3 must not exceed
zlib by more than 2% either)."""
import gzip
import json
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

random.seed(20261115)
inputs = {
    'empty': b'',
    'one': b'x',
    'run': b'a' * 70000,
    'random': random.randbytes(100000),
    'json': json.dumps([{'id': i, 'name': f'user{i}', 'body': 'Tom & Jerry <b>said</b> hi ' * random.randint(1, 4)}
                        for i in range(2000)]).encode(),
    'words': ' '.join(random.choice(['alpha', 'beta', 'gamma', 'the', 'of', 'and']) for _ in range(50000)).encode(),
    'source': (ROOT / 'std/net/http/http.dyn').read_bytes(),
    'large': (ROOT / 'src/backend/ssa.inc').read_bytes()[:300000],
    'binary': Path(DYN).read_bytes()[:400000],
    'short-runs': bytes(random.choice(b'ab') for _ in range(40000)),
    # Small enough for a fixed-Huffman block, with literals from 144 to 255,
    # whose 9-bit fixed codes follow all 288 symbols' 8-bit ones.
    'fixed-high-bytes': b'name \xb1 value ' * 20,
    # Byte i appears fib(i) times: the Huffman tree is far deeper than 15,
    # so the length limit has to repair it into a complete code.
    'fibonacci': bytes(byte for byte, count in enumerate([1, 1, 2, 3, 5, 8, 13, 21, 34, 55, 89, 144, 233, 377, 610,
                                                          987, 1597, 2584, 4181, 6765, 10946, 17711, 28657])
                       for _ in range(count)),
}

with tempfile.TemporaryDirectory(prefix='dyn-deflate-encode-') as temporary:
    work = Path(temporary)
    program = work / 'encode'
    subprocess.run([DYN, 'build', str(ROOT / 'tests/deflate-encode'), '--release', '--quiet', '--no-cache',
                    '--output', str(program)], check=True, timeout=180)
    for name, data in inputs.items():
        source = work / name
        source.write_bytes(data)
        for level in range(1, 10):
            output = work / f'{name}.{level}.gz'
            subprocess.run([str(program), str(level), str(source), str(output)], check=True, timeout=60,
                           capture_output=True)
            packed = output.read_bytes()
            assert gzip.decompress(packed) == data, (name, level)
            reference = len(gzip.compress(data, level, mtime=0))
            assert len(packed) <= reference * 1.02 + 16, (name, level, len(packed), reference)
print('deflate encode ok')
