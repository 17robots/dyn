#!/usr/bin/env python3
"""Primitive allocators: callbacks, typed results, lifecycle and failure behavior."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

LIB = '''use "std/mem"
pub struct State { arena: mem.Arena, calls: usize, last_size: usize, last_alignment: usize }
fn allocate(context: rawptr, size: usize, alignment: usize, error: *AllocError) rawptr {
  state := #cast(*State) context
  state.calls += 1
  state.last_size = size
  state.last_alignment = alignment
  result := mem.arena_push_uninit(&state.arena, size, alignment)
  if !result.ok { error.* = AllocError.Capacity }
  return #cast(rawptr) result.memory
}
pub fn output(state: *State) Allocator { return #allocator(state, &allocate) }
pub fn items(output: Allocator, count: usize) #AllocResult([]u64) {
  return #alloc_slice(u64, output, count)
}
pub fn item(output: Allocator) #AllocResult(*u32) { return #alloc(u32, output) }
pub struct Pair { a: i64, b: i64 }
pub fn mixed(output: Allocator, result: #AllocResult([]u64), a, b, c: i64, pair: Pair) i64 {
  next := #alloc(u8, output)
  if !next.ok || !result.ok { return -1 }
  return a + b + c + pair.a + pair.b + #cast(i64) result.value[3]
}
'''

SOURCE = '''use "std/mem"
use "./lib"
struct Item { tag: u8, number: u64 }
struct Holder { output: Allocator, tag: u8 }
fn expect(ok: bool) { if !ok { #panic("allocator contract") } }
fn reject(context: rawptr, size: usize, alignment: usize, error: *AllocError) rawptr {
  _ = context _ = size _ = alignment
  error.* = AllocError.System
  return nil
}
fn broken(context: rawptr, size: usize, alignment: usize, error: *AllocError) rawptr {
  _ = context _ = size _ = alignment _ = error
  return nil
}
fn once(count: *usize) usize { count.* += 1 return 3 }
fn main() {
  backing: [mem.KiB]u8
  for i in 0..#len(backing) { backing[i] = 165 }
  state := lib.State{ arena: mem.arena_from_buffer(backing[..]) }
  handle := lib.output(&state)
  copy := handle
  holder := Holder{ output: copy }
  expect(#sizeof(Allocator) == 2 * #sizeof(usize))
  expect(#alignof(Allocator) == #alignof(usize))
  handle_info := #typeof(Allocator)
  expect(handle_info.kind == TypeKind.AllocationHandle)
  info := #typeof(#AllocResult([]u64))
  expect(info.kind == TypeKind.AllocationResult && info.member_count == 3)
  expect(#len(info.fields) == 3)
  expect(#len(info.fields[0].name) == 5)
  raw := #alloc_slice_uninit_or_panic(u8, holder.output, 3)
  expect(raw[0] == 165)
  raw_scalar := #alloc_uninit(u8, handle)
  expect(raw_scalar.ok && raw_scalar.value.* == 165)
  raw_slice := #alloc_slice_uninit(u8, handle, 2)
  expect(raw_slice.ok && raw_slice.value[0] == 165)
  raw_pointer := #alloc_uninit_or_panic(u8, handle)
  expect(raw_pointer.* == 165)
  zero_slice := #alloc_slice_or_panic(u8, handle, 2)
  expect(zero_slice[0] == 0 && zero_slice[1] == 0)
  result := lib.items(handle, 4)
  expect(result.ok && result.error == AllocError.None && #len(result.value) == 4)
  expect(result.value[0] == 0 && result.value[3] == 0)
  expect(state.last_size == 4 * #sizeof(u64))
  expect(state.last_alignment == #alignof(u64))
  result.value[3] = 99
  expect(lib.mixed(handle, result, 1, 2, 3, lib.Pair{a: 4, b: 5}) == 114)
  object := #alloc_or_panic(Item, handle)
  expect(object.tag == 0 && object.number == 0)
  expect(#cast(usize) object % #alignof(Item) == 0)
  scalar := lib.item(copy)
  expect(scalar.ok && scalar.value.* == 0)
  calls := state.calls
  used := state.arena.offset
  empty := lib.items(copy, 0)
  expect(empty.ok && #len(empty.value) == 0)
  overflow := lib.items(copy, #cast(usize)-1)
  expect(!overflow.ok && overflow.error == AllocError.Overflow && #len(overflow.value) == 0)
  expect(state.calls == calls && state.arena.offset == used)
  failed := lib.items(copy, mem.KiB)
  expect(!failed.ok && failed.error == AllocError.Capacity && #len(failed.value) == 0)
  expect(state.arena.offset == used && result.value[3] == 99)
  count: usize
  counted := #alloc_slice(u8, handle, once(&count))
  expect(counted.ok && count == 1)
  expect(#alloc(u8, handle).ok)
  spaced := #alloc_or_panic /* slice try_ uninit must not change this builtin */ (u8, handle)
  expect(spaced.* == 0)
  rejecting := #allocator(nil, &reject)
  rejected := #alloc(u8, rejecting)
  expect(!rejected.ok && rejected.error == AllocError.System && rejected.value == nil)
  invalid := #allocator(nil, &broken)
  invalid_result := #alloc(u8, invalid)
  expect(!invalid_result.ok && invalid_result.error == AllocError.InvalidState)
  zero_handle: Allocator
  zero_result := #alloc(u8, zero_handle)
  expect(!zero_result.ok && zero_result.error == AllocError.InvalidState)
  fixed := mem.arena_allocator(&state.arena)
  first := #alloc_or_panic(u32, fixed)
  first.* = 42
  mem.arena_reset(&state.arena)
  second := #alloc_or_panic(u32, fixed)
  expect(second.* == 0)
  growing := mem.growing_create_bounded(mem.KiB, 2 * mem.KiB)
  grow := mem.growing_allocator(&growing)
  defer { expect(mem.growing_release(&growing).ok) }
  for i in 0..50 {
    values := #alloc_slice(u64, grow, 16)
    expect(values.ok && values.value[0] == 0)
    values.value[0] = 123
    mem.growing_reset(&growing)
  }
}
'''

NEGATIVE = {
    'callback': 'fn f() {} fn main() { _ = #allocator(nil, &f) }',
    'dynamic_callback': '''fn f(c: rawptr, s: usize, a: usize, e: *AllocError) rawptr { return nil }
      fn main() { callback := &f _ = #allocator(nil, callback) }''',
    'context': '''fn f(c: rawptr, s: usize, a: usize, e: *AllocError) rawptr { return nil }
      fn main() { _ = #allocator(3, &f) }''',
    'wrong_allocator': 'fn main() { _ = #alloc_or_panic(u32, 1) }',
    'missing_count': 'fn main() { a: Allocator _ = #alloc_slice_or_panic(u32, a) }',
    'extra_count': 'fn main() { a: Allocator _ = #alloc_or_panic(u32, a, 1) }',
    'negative_count': 'fn main() { a: Allocator _ = #alloc_slice_or_panic(u32, a, -1) }',
    'wrong_error': '''fn f(c: rawptr, s: usize, a: usize, e: *u32) rawptr { return nil }
      fn main() { _ = #allocator(nil, &f) }''',
    'foreign_handle': 'extern fn f(a: Allocator) fn main() { a: Allocator f(a) }',
    'opaque': 'fn main() { a: Allocator _ = a.context }',
    'local_escape': '''fn f(c: rawptr, s: usize, a: usize, e: *AllocError) rawptr { return nil }
      fn bad() Allocator { value: u64 return #allocator(&value, &f) } fn main() {}''',
    'adapter_escape': '''use "std/mem"
      fn bad() Allocator { a: mem.Arena return mem.arena_allocator(&a) } fn main() {}''',
    'reset': '''use "std/mem"
      fn main() { b: [128]u8 a := mem.arena_from_buffer(b[..])
        output := mem.arena_allocator(&a) p := #alloc_or_panic(u64, output)
        mem.arena_reset(&a) _ = p.* }''',
}

def run(*args, ok=True):
    result = subprocess.run([DYN, *map(str, args)], capture_output=True, text=True, timeout=90)
    assert (result.returncode == 0) == ok, (args, result.returncode, result.stdout, result.stderr)
    assert result.returncode >= 0, (args, result.stderr)
    return result

with tempfile.TemporaryDirectory(prefix='dyn-allocator-') as temporary:
    root = Path(temporary)
    (root/'lib').mkdir()
    (root/'lib/lib.dyn').write_text(LIB)
    main = root/'main.dyn'
    main.write_text(SOURCE)
    for mode in ('--debug', '--release'):
        run('run', mode, root)
    run('run', '--release', '--no-lto', root)
    index = json.loads(run('query', root).stdout)
    assert any(t['name'] == 'Allocator' for t in index['types'])
    assert any(t['name'] == '#AllocResult([]u64)' for t in index['types'])
    for name, source in NEGATIVE.items():
        main.write_text(source)
        try:
            result = run('check', root, ok=False)
        except AssertionError as error:
            raise AssertionError(name) from error
        assert 'error:' in result.stderr, (name, result.stderr)
    main.write_text('fn main() { a: Allocator _ = #alloc_or_panic(u32, a) }')
    for mode in ('--debug', '--release'):
        result = run('run', mode, root, ok=False)
        assert 'allocation.ok' in result.stderr, result.stderr
    main.write_text('use "std/io"\nfn fail(c: rawptr, s: usize, a: usize, e: *AllocError) rawptr { #panic("callback failed") }\nfn main() {\n  defer { _ = io.println(io.stdout(), "caller cleanup") }\n  _ = #alloc_or_panic(u8, #allocator(nil, &fail))\n}\n')
    for mode in ('--debug', '--release'):
        result = run('run', mode, root, ok=False)
        assert 'caller cleanup' in result.stdout and 'callback failed' in result.stderr, result
    portable = root/'portable' 
    portable.mkdir()
    (portable/'main.dyn').write_text("""struct State { bytes: [128]u8 }
fn allocate(context: rawptr, size: usize, alignment: usize, error: *AllocError) rawptr {
  if size > 128 || alignment > 1 { error.* = AllocError.Capacity return nil }
  state := #cast(*State) context
  return #cast(rawptr) &state.bytes[0]
}
fn main() {
  state: State
  output := #allocator(&state, &allocate)
  bytes := #alloc_slice(u8, output, 8)
  if !bytes.ok { #panic("allocation") }
  bytes.value[0] = 42
}
""")
    for target in ('x86_64-linux', 'aarch64-linux', 'aarch64-macos', 'x86_64-windows', 'wasm32-wasi'):
        run('build', '--target', target, '--emit-object', '--no-link', '--output', root/(target+'.o'), portable)
print('PASS allocator builtins debug/release, negative contracts, and five target object builds')
