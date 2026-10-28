#!/usr/bin/env python3
"""Weak unwind boundaries link and resolve in empty and populated Linux DSOs."""
import ctypes
import importlib.util
import os
from pathlib import Path
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn')).resolve()
if sys.platform != 'linux' or platform.machine() not in ('x86_64', 'amd64'):
    print('SKIP shared unwind boundaries: Linux x86-64 only')
    raise SystemExit(0)
cc = shlex.split(os.environ.get('CC', 'cc'))
if not shutil.which(cc[0]):
    print('SKIP shared unwind boundaries: C linker unavailable')
    raise SystemExit(0)
spec = importlib.util.spec_from_file_location('dyn_runtime_boundaries', ROOT/'tools/native-runtime.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
source = (ROOT/'runtime/linux_x86_64_start.S').read_text()
start = source.index('.section .text.dyn_unwind_tables,')
end = source.index('.section .text.dyn_unwind_set,', start)
with tempfile.TemporaryDirectory(prefix='dyn-shared-boundaries-') as temporary:
    work = Path(temporary)
    assembly = work/'boundaries.S'
    assembly.write_text(source[start:end])
    obj = work/'boundaries.o'
    obj.write_bytes(module.Assembler('x86_64-linux').assemble(assembly, {'__ELF__', 'DYN_SHARED'}).object())
    for populated in (False, True):
        extra = []
        if populated:
            data = work/'table.c'
            data.write_text('__attribute__((used,section("dyn_unwind"))) const unsigned long long entry=42;\n')
            extra = [str(data)]
        library = work/('populated.so' if populated else 'empty.so')
        subprocess.run([*cc, '-shared', str(obj), *extra, '-o', str(library)], check=True, timeout=30)
        loaded = ctypes.CDLL(str(library))
        begin = loaded.dyn_unwind_tables_start
        finish = loaded.dyn_unwind_tables_stop
        begin.restype = finish.restype = ctypes.c_void_p
        first, last = begin(), finish()
        if populated:
            assert first and last and last-first == 8
            assert ctypes.c_uint64.from_address(first).value == 42
        else:
            assert first is None and last is None
        print('PASS shared unwind boundaries:', 'populated' if populated else 'empty')
    # The built-in linker synthesizes these symbols after layout. Its GOT
    # entries must receive the same image-base adjustment as ordinary data.
    table = work/'table.o'
    subprocess.run([*cc, '-fPIC', '-c', str(work/'table.c'), '-o', str(table)], check=True, timeout=30)
    program = work/'program'
    program.mkdir()
    (program/'main.dyn').write_text('''extern fn table_begin "dyn_unwind_tables_start"() rawptr
extern fn table_end "dyn_unwind_tables_stop"() rawptr
pub fn fixture_begin() rawptr {
  return table_begin()
}
pub fn fixture_end() rawptr {
  return table_end()
}
''')
    for mode in ('debug', 'release'):
        library = work/('builtin-'+mode+'.so')
        subprocess.run([str(DYN), 'build', str(program), '--'+mode, '--shared', '--no-cache',
                        '--link', str(table), '--output', str(library)], check=True, timeout=60)
        loaded = ctypes.CDLL(str(library))
        begin, finish = loaded.fixture_begin, loaded.fixture_end
        begin.restype = finish.restype = ctypes.c_void_p
        first, last = begin(), finish()
        entry = ctypes.addressof(ctypes.c_uint64.in_dll(loaded, 'entry'))
        assert first and last and first <= entry < last, (first, entry, last)
        print('PASS built-in shared unwind boundaries:', mode)
