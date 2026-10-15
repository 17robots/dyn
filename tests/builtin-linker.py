#!/usr/bin/env python3
"""x86-64 Linux executables link in-process: no external linker on PATH,
archive members load on demand, unused sections are dropped, and link errors
name the symbol."""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
CC = os.environ.get('CC', 'cc')

if not sys.platform.startswith('linux') or os.uname().machine != 'x86_64':
    print('SKIP built-in linker: needs an x86-64 Linux host')
    sys.exit(0)

USED = r'''
int dyn_fixture_counter;
int dyn_fixture_table[4] = {1, 2, 3, 4};
const int *dyn_fixture_pointer = &dyn_fixture_table[2];
int dyn_fixture_helper(int value);
__attribute__((weak)) int dyn_fixture_optional(int value);
int dyn_fixture_dropped(int value) { return value * 7; }
int dyn_fixture_used(int value) {
  dyn_fixture_counter += value;
  int optional = dyn_fixture_optional ? dyn_fixture_optional(value) : 100;
  return dyn_fixture_helper(value) + *dyn_fixture_pointer + optional + dyn_fixture_counter;
}
'''
HELPER = r'''
int dyn_fixture_helper(int value) { return value * 2; }
'''
UNUSED = r'''
int dyn_fixture_unused(int value) { return value - 1; }
'''
DUPLICATE = r'''
int dyn_fixture_helper(int value) { return value; }
'''
MAIN = '''extern fn used "dyn_fixture_used"(value: i32) i32
fn main() {
  // helper 10, table 3, weak fallback 100, counter 5.
  if used(5) != 118 { #panic("first call") }
  if used(1) != 111 { #panic("second call") }
}
'''
MISSING = '''extern fn missing "dyn_fixture_missing"(value: i32) i32
fn main() {
  if missing(1) != 0 { #panic("unreachable") }
}
'''


def run(*args, ok=True, **kwargs):
    process = subprocess.run([str(arg) for arg in args], capture_output=True, text=True, timeout=120, **kwargs)
    assert (process.returncode == 0) == ok, (args, process.returncode, process.stdout + process.stderr)
    return process


def symbols(path):
    if not shutil.which('readelf'):
        return None
    table = run('readelf', '-sW', path).stdout
    return {line.split()[-1] for line in table.splitlines() if line.split()[-1:]}


with tempfile.TemporaryDirectory(prefix='dyn-builtin-linker-') as temporary:
    root = Path(temporary)
    flags = ['-c', '-O1', '-ffreestanding', '-fno-stack-protector', '-ffunction-sections', '-fdata-sections']
    for name, text in (('used', USED), ('helper', HELPER), ('unused', UNUSED), ('duplicate', DUPLICATE)):
        (root/f'{name}.c').write_text(text)
        run(CC, *flags, root/f'{name}.c', '-o', root/f'{name}.o')
    run('ar', 'rcs', root/'libfixture.a', root/'helper.o', root/'unused.o')
    for name, text in (('program', MAIN), ('missing', MISSING)):
        (root/name).mkdir()
        (root/name/'main.dyn').write_text(text)
    # An empty PATH proves no linker is spawned.
    bare = dict(os.environ, PATH=str(root/'empty'))
    output = root/'program.out'
    process = run(DYN, 'build', root/'program', '--output', output, '--verbose',
                  '--link', root/'used.o', '--link', root/'libfixture.a', env=bare)
    assert '(built-in) link' in process.stderr, process.stderr
    run(output)
    names = symbols(output)
    if names is not None:
        assert 'dyn_fixture_used' in names and 'dyn_fixture_helper' in names, names
        assert 'dyn_fixture_unused' not in names, 'archive member loaded without a reference'
        assert 'dyn_fixture_dropped' not in names, 'unreferenced section kept'
    if shutil.which('ld.lld'):
        reference = root/'reference.out'
        run(DYN, 'build', root/'program', '--output', reference, '--link', root/'used.o',
            '--link', root/'libfixture.a', env=dict(os.environ, DYN_LINKER='external'))
        run(reference)
    process = run(DYN, 'build', root/'missing', '--output', root/'missing.out', env=bare, ok=False)
    assert "undefined symbol 'dyn_fixture_missing'" in process.stderr, process.stderr
    assert not (root/'missing.out').exists() and not (root/'missing.out.tmp').exists()
    process = run(DYN, 'build', root/'program', '--output', root/'duplicate.out', '--link', root/'used.o',
                  '--link', root/'helper.o', '--link', root/'duplicate.o', env=bare, ok=False)
    assert "duplicate symbol 'dyn_fixture_helper'" in process.stderr, process.stderr

print('PASS built-in x86-64 linker: no external linker, lazy archives, section GC and link errors')
