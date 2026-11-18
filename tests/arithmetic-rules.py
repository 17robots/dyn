#!/usr/bin/env python3
"""Target-typed arithmetic, signed/unsigned comparison and x % M narrowing,
in debug, release and on WebAssembly."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = (ROOT / 'tests/arithmetic-rules/expected.txt').read_text()
WASI = ("const {WASI}=require('node:wasi');const fs=require('node:fs');"
        "const w=new WASI({version:'preview1',args:[]});"
        "WebAssembly.instantiate(fs.readFileSync(process.argv[1]),w.getImportObject())"
        ".then(({instance})=>w.start(instance));")
with tempfile.TemporaryDirectory(prefix='dyn-arithmetic-rules-') as temporary:
    root = Path(temporary)
    for name, flags, runner in (('debug', ['--debug'], []), ('release', ['--release'], []),
                                ('wasi.wasm', ['--target', 'wasm32-wasi'], ['node', '--no-warnings', '-e', WASI])):
        program = root / name
        subprocess.run([DYN, 'build', str(ROOT / 'tests/arithmetic-rules'), *flags, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=120)
        if runner and not shutil.which(runner[0]):
            continue
        result = subprocess.run([*runner, str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == EXPECTED, (name, result.stdout, result.stderr)
    bad = root / 'bad'
    bad.mkdir()
    cases = {
        # Neither side can be read twice.
        'fn s() i64 {\n  return -1\n}\nfn u() u64 {\n  return 1\n}\nfn main() {\n  _ = s() < u()\n}\n':
            'store one in a name first',
        # u64 and i64 still have no lossless meeting type for arithmetic.
        'fn main() {\n  a: u64 = 1\n  b: i64 = 2\n  _ = a + b\n}\n': 'mismatched types u64 and i64',
        # Only unsigned x % M narrows.
        'fn main() {\n  a: i32 = -7\n  b: u8 = a % 5\n  _ = b\n}\n': 'expected u8',
    }
    for source, message in cases.items():
        (bad / 'main.dyn').write_text(source)
        checked = subprocess.run([DYN, 'check', str(bad)], capture_output=True, text=True, timeout=60)
        assert checked.returncode != 0 and message in checked.stderr, (source, checked.stderr)
print('PASS arithmetic rules: target-typed arithmetic, signed/unsigned comparison, x % M (debug/release/wasm)')
