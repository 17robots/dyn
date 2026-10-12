#!/usr/bin/env python3
"""Frontend regressions for declaration order, dependency cycles and type IDs."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())


def project(root, name, source):
    directory = root / name
    directory.mkdir()
    (directory / 'main.dyn').write_text(source)
    return directory


def check(directory, expected=None):
    result = subprocess.run([DYN, 'check', str(directory)], capture_output=True,
                            text=True, timeout=60)
    if expected is None:
        assert result.returncode == 0, (directory.name, result.stderr)
    else:
        assert result.returncode == 1, (directory.name, result.returncode, result.stderr)
        assert expected in result.stderr, (directory.name, result.stderr)


def run(directory):
    for release in (False, True):
        output = directory / ('run-release' if release else 'run-debug')
        result = subprocess.run(
            [DYN, 'build', str(directory), '--quiet', '--no-cache', '--output', str(output)]
            + (['--release'] if release else []), capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, (directory.name, release, result.stderr)
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=10)
        assert result.returncode == 0, (directory.name, release, result.stderr)


with tempfile.TemporaryDirectory(prefix='dyn-frontend-audit-') as temporary:
    root = Path(temporary)
    run(project(root, 'forward-layout', '''struct Wrapper { value: Later }
enum Early { Value: Wrapper }
enum Later { Value }
fn main() {
  value := Early.Value(Wrapper{value: Later.Value})
  case value { Early.Value payload => { if payload.value != Later.Value { #panic("layout") } } }
}
'''))
    run(project(root, 'forward-globals', '''const a := b + 1
const b := c
const c := 41
struct Defaults { value: i64 = a }
fn main() {
  value := Defaults{}
  if a != 42 || b != 41 || value.value != 42 { #panic("forward global") }
}
'''))
    # Both directions must work, including globals with explicit types.
    run(project(root, 'backward-globals', '''const c: i64 = 41
const b := c
const a := b + 1
fn main() { if a != 42 { #panic("backward global") } }
'''))
    check(project(root, 'inferred-cycle', '''const a := b
const b := a
fn main() {}
'''), 'cyclic inferred global type dependency')
    check(project(root, 'typed-cycle', '''const a: i64 = b
const b: i64 = a
fn main() {}
'''), 'constant initializer must be compile-time expression')
    check(project(root, 'layout-cycle', '''struct Wrapper { value: Recursive }
enum Recursive { Value: Wrapper }
fn main() {}
'''), 'contains itself by value')
    check(project(root, 'pointer-layout-cycle', '''struct Node { next: *Node }
fn main() {}
'''))
    # 256..32767 are struct IDs; the following ID belongs to enums.
    declarations = ''.join(f'struct S{i} {{}}\n' for i in range(32512))
    check(project(root, 'struct-capacity-boundary', declarations + 'fn main() {}\n'))
    check(project(root, 'struct-capacity-overflow', declarations +
                  'struct Overflow {}\nfn main() {}\n'), 'struct type capacity exceeded')
    run(project(root, 'assert-pass', '''#assert(#sizeof(Header) == 12 && #alignof(Header) == 1, "packed header")
packed struct Header { tag: u32, size: u64 }
const COUNT: usize = 4
const OFFSET: i32 = -3
#assert(COUNT * #sizeof(u32) <= 16)
#assert(OFFSET < 0 && !(OFFSET * 2 > -6))
fn main() {}
'''))
    check(project(root, 'assert-fail', '''struct Header { tag: u32, size: u64 }
#assert(#sizeof(Header) == 12, "header layout changed")
fn main() {}
'''), '#assert failed: header layout changed')
    check(project(root, 'assert-runtime', '''#assert(answer() == 1)
fn answer() i32 { return 1 }
fn main() {}
'''), '#assert condition must be a compile-time constant')
    run(project(root, 'offsetof', '''struct Header { tag: u8, size: u64, flags: u16 }
packed struct Packed { tag: u8, size: u64 }
#assert(#offsetof(Header, size) == 8 && #offsetof(Header, flags) == 16)
#assert(#offsetof(Packed, size) == 1)
fn main() {
  h: Header
  if #cast(usize) &h.flags - #cast(usize) &h != #offsetof(Header, flags) { #panic("offset") }
  p: Packed
  if #cast(usize) &p.size - #cast(usize) &p != #offsetof(Packed, size) { #panic("packed") }
}
'''))
    check(project(root, 'offsetof-field', '''struct A { x: u8 }
#assert(#offsetof(A, y) == 0)
fn main() {}
'''), '#offsetof names an unknown field')
    check(project(root, 'offsetof-type', '''#assert(#offsetof(u8, x) == 0)
fn main() {}
'''), '#offsetof requires a struct type')
    check(project(root, 'assert-type', '''#assert(#sizeof(u8))
fn main() {}
'''), '#assert condition must be bool')

print('PASS frontend audit: declaration order, cycles, type capacity, #assert, #offsetof')
