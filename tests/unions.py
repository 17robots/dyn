#!/usr/bin/env python3
"""Pointer-free unions: layout, overlays, by-value use and rejected members."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-unions-') as temporary:
    root = Path(temporary)
    for mode in ('--debug', '--release'):
        program = root / ('program' + mode)
        subprocess.run([DYN, 'build', str(ROOT / 'tests/unions'), mode, '--quiet', '--no-cache',
                        '--output', str(program)], check=True, timeout=120)
        subprocess.run([str(program)], check=True, timeout=30)
    module = root / 'bad'
    module.mkdir()
    for source, message in (('union U { p: *u8 }\n', 'cannot hold pointers'), ('union U { s: []u8 }\n', 'cannot hold pointers'),
                            ('struct S { p: *u8 }\nunion U { s: S }\n', 'cannot hold pointers'),
                            ('union U { a: u8, b: u8 }\nfn f() U { return U{ a: 1, b: 2 } }\n', 'sets one member')):
        (module / 'main.dyn').write_text(source + 'fn main() {}\n')
        checked = subprocess.run([DYN, 'check', str(module)], capture_output=True, text=True, timeout=60)
        assert checked.returncode != 0 and message in checked.stderr, (source, checked.stderr)
print('PASS unions: overlays, layout, by-value copies, nesting and pointer rejection (debug/release)')
