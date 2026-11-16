#!/usr/bin/env python3
"""for i in #step(range, n): forward, inclusive, reversed, empty, signed, at the
type's limit and with continue/break, in debug, release and on WebAssembly."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
EXPECTED = (ROOT / 'tests/step-loops/expected.txt').read_text()
WASI = ("const {WASI}=require('node:wasi');const fs=require('node:fs');"
        "const w=new WASI({version:'preview1',args:[]});"
        "WebAssembly.instantiate(fs.readFileSync(process.argv[1]),w.getImportObject())"
        ".then(({instance})=>w.start(instance));")
with tempfile.TemporaryDirectory(prefix='dyn-step-loops-') as temporary:
    root = Path(temporary)
    for name, flags, runner in (('debug', ['--debug'], []), ('release', ['--release'], []),
                                ('checked', ['--check-overflow'], []),
                                ('wasi.wasm', ['--target', 'wasm32-wasi'], ['node', '--no-warnings', '-e', WASI])):
        program = root / name
        subprocess.run([DYN, 'build', str(ROOT / 'tests/step-loops'), *flags, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=120)
        if runner and not shutil.which(runner[0]):
            continue
        result = subprocess.run([*runner, str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0 and result.stdout == EXPECTED, (name, result.stdout, result.stderr)
    bad = root / 'bad'
    bad.mkdir()
    cases = {
        'fn main() {\n  for i in #step(0..10, 0) {\n    _ = i\n  }\n}\n': 'positive step',
        'fn main() {\n  for i: i32 in #step(0..10, -2) {\n    _ = i\n  }\n}\n': 'positive step',
        'fn main() {\n  n: u8 = 2\n  for i: i32 in #step(0..10, n) {\n    _ = i\n  }\n}\n': "range's type",
        'fn main() {\n  for i in #step(#reverse(0..10), 2) {\n    _ = i\n  }\n}\n': '#reverse is valid only',
    }
    for source, message in cases.items():
        (bad / 'main.dyn').write_text(source)
        checked = subprocess.run([DYN, 'check', str(bad)], capture_output=True, text=True, timeout=60)
        assert checked.returncode != 0 and message in checked.stderr, (source, checked.stderr)
print('PASS #step loops (debug/release/checked/wasm)')
