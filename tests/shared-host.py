#!/usr/bin/env python3
"""A native host loads debug/release Dyn exports without unresolved runtime symbols."""
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
with tempfile.TemporaryDirectory(prefix='dyn-shared-host-') as temporary:
    root = Path(temporary)
    (root / 'main.dyn').write_text('''
stored: i32 = initial()
fn initial() i32 { return 42 }
fn main() { stored += 1 }
pub fn initialized() i32 { return stored }
pub fn add(a: i32, b: i32) i32 { return a + b }
pub fn invoke(callback: *fn(i32) i32, value: i32) i32 { return callback(value) }
''')
    suffix = '.dll' if os.name == 'nt' else '.dylib' if sys.platform == 'darwin' else '.so'
    for mode in ('debug', 'release'):
        output = root / (mode + suffix)
        subprocess.run([str(DYN), 'build', str(root), '--shared', '--' + mode,
                        '--jobs', '1', '--output', str(output)], check=True, timeout=30)
        # Child process unloads all libraries before the temporary directory is removed on Windows.
        subprocess.run([sys.executable, '-c', '''
import ctypes as c, sys
library = c.CDLL(sys.argv[1])
assert library.initialized() == 42
library.main()
library.main()
assert library.initialized() == 44
library.add.argtypes = [c.c_int32, c.c_int32]
library.add.restype = c.c_int32
assert library.add(19, 23) == 42
callback_type = c.CFUNCTYPE(c.c_int32, c.c_int32)
callback = callback_type(lambda value: value + 1)
library.invoke.argtypes = [callback_type, c.c_int32]
library.invoke.restype = c.c_int32
assert library.invoke(callback, 41) == 42
''', str(output)], check=True, timeout=10)
print('PASS native host loading and callbacks in debug/release shared libraries')
