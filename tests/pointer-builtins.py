#!/usr/bin/env python3
"""#slice, #offset and pointer ordering; pointers cannot be sliced with brackets."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-pointer-builtins-') as temporary:
    root = Path(temporary)
    for mode in ('--debug', '--release'):
        program = root / ('program' + mode)
        subprocess.run([DYN, 'build', str(ROOT / 'tests/pointer-builtins'), mode, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=120)
        subprocess.run([str(program)], check=True, timeout=30)
    errors = {'x: i32 = 1\n  p := &x\n  _ = p[..1]': '#slice(pointer, count)',
              'x: [2]i32 = []\n  _ = #slice(x, 1)': 'require a pointer',
              'x: i32 = 1\n  _ = #offset(&x, 1.5)': ''}
    module = root / 'bad'
    module.mkdir()
    for body, message in errors.items():
        (module / 'main.dyn').write_text('fn main() {\n  ' + body + '\n}\n')
        checked = subprocess.run([DYN, 'check', str(module)], capture_output=True, text=True, timeout=60)
        assert checked.returncode != 0 and message in checked.stderr, (body, checked.stderr)
print('PASS pointer builtins: #slice, #offset, ordering and bracket rejection (debug/release)')
