#!/usr/bin/env python3
"""x86-64 Linux executables link in-process: no external linker on PATH,
archive members load on demand, unused sections are dropped, link errors name
the symbol, and release ThinLTO output matches ld.lld's."""
import os
import re
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
RELEASE = '''use "std/io" io
use "std/mem" mem
fn mix(x: u64) u64 {
  return (x ^ 0x9e3779b9) * 2654435761
}
fn main() {
  arena := mem.arena_create(4096)
  values := mem.arena_push(&arena, 64, 8)[..64]
  state: u64 = 1
  for i in 0..64 {
    state = mix(state + #cast(u64) i) % 1000003
    values[i] = #cast(u8) state
  }
  _ = io.println(io.stdout(), "{}", state)
  mem.arena_release(&arena)
}
'''
LIBRARY = r'''
int dyn_shared_value = 41;
int dyn_shared_add(int value) { return value + dyn_shared_value; }
int dyn_shared_call(int (*callback)(int)) { dyn_shared_value += 1; return callback(dyn_shared_value); }
'''
READER = r'''
extern int dyn_shared_value;
int dyn_fixture_read(void) { return dyn_shared_value; }
'''
DYNAMIC = '''extern fn add "dyn_shared_add"(value: i32) i32
extern fn call "dyn_shared_call"(callback: *fn(i32) i32) i32
extern fn read "dyn_fixture_read"() i32
fn twice(value: i32) i32 {
  return value * 2
}
fn main() {
  if add(1) != 42 { #panic("PLT call") }
  if read() != 41 { #panic("copied data") }
  if call(&twice) != 84 { #panic("callback") }
  // The library writes the executable's copy, so both sides agree.
  if read() != 42 { #panic("shared copy") }
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
    # A PATH holding only Python (for wrapper compilers) proves no linker is spawned.
    (root/'bin').mkdir()
    (root/'bin'/'python3').symlink_to(sys.executable)
    bare = dict(os.environ, PATH=str(root/'bin'))
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

    # Shared libraries: PLT calls, a function pointer passed back in, data
    # read directly by non-PIC code (a copy relocation), and the C library
    # through its GROUP linker script.
    (root/'library.c').write_text(LIBRARY)
    run(CC, '-shared', '-fPIC', '-O1', root/'library.c', '-o', root/'libdynfixture.so')
    (root/'reader.c').write_text(READER)
    run(CC, *flags, '-fno-pic', root/'reader.c', '-o', root/'reader.o')
    (root/'dynamic').mkdir()
    (root/'dynamic'/'main.dyn').write_text(DYNAMIC)
    libc = next((path for path in ('/usr/lib/x86_64-linux-gnu/libc.so', '/usr/lib64/libc.so', '/usr/lib/libc.so')
                 if Path(path).exists()), None)
    inputs = ['--link', root/'reader.o', '--link', root/'libdynfixture.so']
    if libc:
        inputs += ['--link', libc]
    for mode in ([], ['--release']):
        dynamic = root/'dynamic.out'
        run(DYN, 'build', root/'dynamic', '--output', dynamic, *mode, *inputs, env=bare)
        run(dynamic)
        if shutil.which('readelf'):
            relocations = run('readelf', '-rW', dynamic).stdout
            assert 'R_X86_64_COPY' in relocations and 'R_X86_64_JUMP_SLOT' in relocations, relocations

    # Release: in-process ThinLTO must produce the same code, in the same
    # order, as ld.lld's ThinLTO, with and without a call-graph profile.
    (root/'release').mkdir()
    (root/'release'/'main.dyn').write_text(RELEASE)
    if shutil.which('ld.lld') and shutil.which('objdump') and shutil.which('nm'):
        profile = root/'sample.prof'
        profile.write_text('main:1000000:1\n' + ''.join(f' {line}: 1000\n' for line in range(40)))

        def code(path):
            listing = run('objdump', '-d', '--no-show-raw-insn', path).stdout
            lines = []
            for line in listing.splitlines():
                if ':\t' not in line or 'int3' in line:
                    continue
                text = line.split(':\t', 1)[1]
                lines.append(re.sub(r'<[^>]*>', '', re.sub(r'[0-9a-f]{6,}', 'A', re.sub(r'0x[0-9a-f]+', 'X', text))))
            order = [line.split()[2] for line in run('nm', '-n', path).stdout.splitlines()
                     if len(line.split()) == 3 and line.split()[1] in 'tT']
            return lines, order

        for name, extra in (('plain', []), ('profiled', ['--sample-profile', profile])):
            ours, theirs = root/f'{name}-builtin', root/f'{name}-lld'
            run(DYN, 'build', root/'release', '--release', '--output', ours, *extra, env=dict(bare, DYN_CACHE_DIR=str(root/f'{name}-a')))
            run(DYN, 'build', root/'release', '--release', '--output', theirs, *extra,
                env=dict(os.environ, DYN_LINKER='external', DYN_CACHE_DIR=str(root/f'{name}-b')))
            assert run(ours).stdout == run(theirs).stdout
            assert code(ours) == code(theirs), f'{name}: in-process ThinLTO differs from ld.lld'

    # AArch64 Linux: same instructions as ld.lld, debug and release, run
    # under qemu (relaxed adrp pairs included).
    if shutil.which('ld.lld') and shutil.which('llvm-objdump') and shutil.which('qemu-aarch64'):
        def arm_code(path):
            listing = run('llvm-objdump', '-d', '--no-show-raw-insn', path).stdout
            lines = []
            for line in listing.splitlines():
                if not re.match(r'^\s+[0-9a-f]+:', line):
                    continue
                text = re.sub(r'^\s+[0-9a-f]+:\s+', '', line)
                text = re.sub(r'<[^>]*>', '', re.sub(r'[0-9a-f]{6,}', 'A', re.sub(r'#-?[0-9]+', '#N', re.sub(r'0x[0-9a-f]+', 'X', text))))
                lines.append(text.rstrip())
            return lines

        for mode in ([], ['--release']):
            ours, theirs = root/'arm-builtin', root/'arm-lld'
            run(DYN, 'build', root/'release', '--target', 'aarch64-linux', '--output', ours, *mode,
                env=dict(bare, DYN_CACHE_DIR=str(root/'arm-a')))
            run(DYN, 'build', root/'release', '--target', 'aarch64-linux', '--output', theirs, *mode,
                env=dict(os.environ, DYN_LINKER='external', DYN_CACHE_DIR=str(root/'arm-b')))
            assert run('qemu-aarch64', ours).stdout == run('qemu-aarch64', theirs).stdout
            assert arm_code(ours) == arm_code(theirs), f'AArch64 {mode}: built-in link differs from ld.lld'

print('PASS built-in x86-64/AArch64 linker and in-process ThinLTO: no external linker, lazy archives, section GC, link errors, shared libraries, lld code parity')
