#!/usr/bin/env python3
"""Assembly export across targets: native object preservation and safe publication.

The compiler writes assembly with a PATH that contains no external tools.
"""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn')).resolve())
SOURCE = r'''
struct Pair { integer: i64, real: f64 }
struct Large { bytes: [40]u8, value: i64 }
struct Floats { x:f32, y:f32 }
packed struct Packed { small: u8, wide: i64 }
enum(i8) Sign { Minus = -1, Zero = 0, Plus = 1 }
extern fn provider "provider"(x: Pair) Pair
extern fn floats_provider "floats_provider"(x:Floats) Floats
extern fn large_provider "large_provider"(x: Large) Large
extern fn packed_provider "packed_provider"(x: Packed) Packed
counter: i32 = 0
message: []const u8 = "bytes\x00with null"
fn first(x: i32) i32 { return x + 2 }
callback: fn(i32) i32 = &first
fn add(p: *i32) { p.* += 1 }
fn cleanup() { counter += 1 }
fn checked(x: i32) i32 { defer cleanup() return 12 / x }
fn aggregate(x: Pair) Pair { value := x value.integer += 1 return value }
fn main() {
  floats := floats_provider(Floats{x:1.25,y:2.5})
  if floats.x != 2.25 || floats.y != 3.5 { #panic("HFA") }
  defer cleanup()
  original := Pair{integer: 7, real: 2.5}
  local := aggregate(original)
  foreign := provider(original)
  indirect := &provider
  foreign = indirect(foreign)
  if original.integer != 7 || local.integer != 8 || foreign.integer != 9 || foreign.real != 4.5 { #panic("pair ABI") }
  large := Large{value: 41}
  large.bytes[39] = 7
  other := large_provider(large)
  if large.value != 41 || other.value != 42 || other.bytes[39] != 7 { #panic("large byval ABI") }
  packed := packed_provider(Packed{small: 3, wide: 8})
  if packed.small != 3 || packed.wide != 9 { #panic("packed ABI") }
  values := [1, 2, 3, 4]
  sum: i32 = 0
  for value in values { sum += value }
  for i in 0..3 { sum += #cast(i32, i) }
  if sum != 13 { #panic("loops") }
  ptr := &sum
  add(ptr)
  if ptr.* != 14 || callback(3) != 5 { #panic("pointer") }
  sign := #cast(Sign, -1)
  if #cast(i8, sign) != -1 { #panic("signed enum") }
  number: f32 = 1.25
  wide := #cast(f64, number)
  if wide + 0.75 != 2.0 || #cast(i32, wide) != 1 { #panic("float") }
  if checked(3) != 4 || counter != 1 || #len(message) != 15 { #panic("cleanup globals") }
}
'''
TARGETS = [('x86_64-linux', 'x86_64-unknown-linux-gnu'),
           ('aarch64-linux', 'aarch64-unknown-linux-gnu'),
           ('riscv64-linux', 'riscv64-unknown-linux-gnu'),
           ('x86_64-macos', 'x86_64-apple-macos15'),
           ('aarch64-windows', 'aarch64-pc-windows-msvc'),
           ('aarch64-macos', 'arm64-apple-macos11'),
           ('x86_64-windows', 'x86_64-pc-windows-msvc'),
           ('wasm32-wasi', 'wasm32-unknown-wasi'),
           ('wasm32-browser', 'wasm32-unknown-unknown')]

def run(args, **kwargs):
    result = subprocess.run(list(map(str,args)), capture_output=True, text=True,
                            timeout=60, **kwargs)
    assert result.returncode == 0, (args, result.stdout, result.stderr)
    return result

with tempfile.TemporaryDirectory(prefix='dyn-text-') as directory:
    work = Path(directory)
    module = work/'module'
    module.mkdir()
    (module/'main.dyn').write_text(SOURCE)
    empty = work/'empty-path'
    empty.mkdir()
    env = dict(os.environ, DYN_SDK=str(ROOT), PATH=str(empty))
    # Windows needs DLL lookup through its normal PATH.
    if os.name == 'nt':
        env['PATH'] = os.environ.get('PATH','')
    for target, triple in TARGETS:
        for release in (False, True):
            output = work/(target + ('-release' if release else '-debug'))
            flags = ['--backend','native','--target',target,'--no-cache',
                     '--emit-object','--no-link','--output',output]
            if release:
                flags += ['--release', '--debug-info']
            if target == 'wasm32-browser':
                flags += ['--shared']
            run([DYN,'build',module,*flags],env=env,cwd=ROOT)
            object_path = Path(str(output)+'.o')
            original = object_path.read_bytes()
            run([DYN,'build',module,*flags,'--emit-asm'],env=env,cwd=ROOT)
            assert object_path.read_bytes() == original, 'assembly export replaced native object'
            text = Path(str(output)+'.s').read_text()
            assert 'checked' in text and 'aggregate' in text, text[:2000]
    # Failed publication cannot remove an existing destination or leak staging
    # files. A directory destination fails identically across supported hosts.
    blocked = work/'blocked.s'
    blocked.mkdir()
    (blocked/'sentinel').write_text('keep')
    result = subprocess.run([DYN,'build',str(module),'--backend','native',
                             '--emit-asm','--no-link','--output',str(work/'blocked')],
                            env=env,cwd=ROOT,capture_output=True,text=True)
    assert result.returncode != 0
    assert (blocked/'sentinel').read_text() == 'keep'
    assert not list(work.glob('.dyn-object.*'))
    # Failed frontend input must leave a previously published sidecar intact.
    sentinel = work/'preserved.s'
    sentinel.write_text('previous successful export\n')
    (module/'main.dyn').write_text('fn main( { invalid')
    result = subprocess.run([DYN,'build',str(module),'--backend','native',
                             '--emit-asm','--no-link','--output',str(work/'preserved')],
                            env=env,cwd=ROOT,capture_output=True,text=True)
    assert result.returncode != 0
    assert sentinel.read_text() == 'previous successful export\n'
print('PASS assembly export across nine targets: native object preservation and safe publication')
