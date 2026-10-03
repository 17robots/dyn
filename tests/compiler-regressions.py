#!/usr/bin/env python3
"""Regressions: C exit handlers, extern name clashes, global shadowing, literal operand types, hex literals."""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())


def project(root, name, files):
    directory = root/name
    for path, text in files.items():
        (directory/path).parent.mkdir(parents=True, exist_ok=True)
        (directory/path).write_text(text)
    return directory


def build_and_run(directory):
    for release in (False, True):
        output = directory/('run-release' if release else 'run')
        subprocess.run([DYN, 'build', str(directory), '--quiet', '--no-cache', '--output', str(output)] +
                       (['--release'] if release else []), check=True, timeout=60)
        result = subprocess.run([str(output)], stdout=subprocess.PIPE, timeout=10)
        assert result.returncode == 0, (directory.name, release, result.returncode)
        yield result.stdout


def check_fails(directory, expected):
    result = subprocess.run([DYN, 'check', str(directory)], capture_output=True, text=True, timeout=60)
    errors = [line for line in result.stderr.splitlines() if 'error:' in line]
    assert result.returncode == 1, (directory.name, result.stderr)
    assert len(errors) == 1 and expected in errors[0], (directory.name, result.stderr)


with tempfile.TemporaryDirectory(prefix='dyn-compiler-regressions-') as temporary:
    root = Path(temporary)

    # Process exit goes through the C library when it is linked, so buffered
    # stdio reaches a pipe.
    streams = project(root, 'exit-flush', {'main.dyn': '''#link("c")
extern fn puts(text: *const u8) i32
fn main() {
  text := "buffered\\0"
  _ = puts(&text[0])
}
'''})
    for output in build_and_run(streams):
        assert output == b'buffered\n', output

    # A Dyn function may share its name with an extern's C symbol declared in
    # another file of the same module.
    clash = project(root, 'extern-clash', {'main.dyn': '''#link("c")
pub fn free(pointer: rawptr) {
  release(pointer)
}
fn main() {
  free(allocate(16))
}
''', 'other.dyn': '''extern fn libc_malloc "malloc"(size: usize) rawptr
extern fn libc_free "free"(pointer: rawptr)
fn allocate(size: usize) rawptr {
  return libc_malloc(size)
}
fn release(pointer: rawptr) {
  libc_free(pointer)
}
'''})
    for _ in build_and_run(clash):
        pass

    # Parameters may not shadow globals, in the root module and in imports.
    shadow = 'parameter has the name of a global'
    check_fails(project(root, 'shadow-root', {'main.dyn': '''output: [16]u8 = []
fn encode(character: u32, output: []u8) usize {
  output[0] = #cast(u8) character
  return 1
}
fn main() {
  storage: [4]u8 = []
  _ = encode(65, storage[..])
}
'''}), shadow)
    check_fails(project(root, 'shadow-import', {'main.dyn': '''use "lib"
fn main() {
  _ = lib.count(3)
}
''', 'lib/lib.dyn': '''total: usize = 0
pub fn count(total: usize) usize {
  return total
}
'''}), shadow)

    # A numeric literal adopts the other operand's type on either side; e and E
    # are digits in hex literals, not exponents.
    literals = project(root, 'literal-left', {'main.dyn': '''use "std/os/linux" os
fn check() u8 {
  step: u32 = 3
  big: u64 = 5000000000
  f: f64 = 1.5
  b: u8 = 200
  a := 8 + step * 10
  c := 100 - step
  d := 1.0 + f
  e := -1 + 0
  g := 6000000000 + big
  h := 255 - b
  m := ~0 & b
  x: u32 = 0x1E1E2E
  y: [2]u32 = [0xE, 0x1e]
  if !(2 < step && 10 >= step) { return 1 }
  if a != 38 { return 2 }
  if c != 97 { return 3 }
  if d != 2.5 { return 4 }
  if e != -1 { return 5 }
  if g != 11000000000 { return 6 }
  if h != 55 { return 7 }
  if m != 200 { return 8 }
  if x != 1973806 || y[0] != 14 || y[1] != 30 { return 9 }
  return 0
}
fn main() { os.exit_process(check()) }
'''})
    for _ in build_and_run(literals):
        pass
    check_fails(project(root, 'literal-range', {'main.dyn': '''fn main() {
  b: u8 = 1
  _ = 300 + b
}
'''}), 'not representable')

print('PASS compiler regressions: exit flush, extern clash, global shadowing, literal operands')
