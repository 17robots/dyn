#!/usr/bin/env python3
"""End-to-end tests for Phase 2: <T> generics, compile-time case T, str,
std/slice, and std/collections."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN_DEBUG = str(Path(os.environ.get('DYN_DEBUG', ROOT / 'build/dyn')).resolve())
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

PROGRAM = r'''
use col "std/collections"
use mem "std/mem"
use slice "std/slice"

struct Pair<A, B> {
  first: A,
  second: B,
}

enum Slot<T> {
  Empty,
  Full(T),
}

fn max_of<T>(a: T, b: T) T {
  if a > b { return a }
  return b
}

fn zero_of<T>() T {
  v: T
  return v
}

fn narrow_to<T, U>(x: U) T {
  return #cast(T, x)
}

fn hash_tag<K>(key: K) u64 {
  case K {
    str, []u8 => { return #cast(u64, key.len) + 100 }
    bool => {
      if key { return 201 }
      return 200
    }
    i32, u32 => { return #cast(u64, key) + 300 }
    _ => { #assert(false, "unsupported key type in hash_tag") }
  }
}

fn double_it<T>(x: T) T {
  return x + x
}

fn apply_u32(f: fn(u32) u32, x: u32) u32 {
  return f(x)
}

fn main() {
  arena := mem.arena_alloc(4 * mem.MiB)
  defer mem.arena_release(arena)

  // 1. Inferred & explicit <T> calls + partial explicit type args
  if max_of(3, 9) != 9 { #panic("max inferred") }
  if max_of<i64>(10, 4) != 10 { #panic("max explicit") }
  if zero_of<u32>() != 0 { #panic("zero_of") }
  if narrow_to<u8>(65) != 65 { #panic("partial explicit type args") }

  // 2. Generic struct & enum literals + nested >> closing
  p := Pair<str, u32>{ first: "dyn", second: 42 }
  if p.first.len != 3 || p.second != 42 { #panic("Pair<str, u32>") }
  nested := Pair<str, Pair<u8, u16>>{ first: "ok", second: Pair<u8, u16>{ first: 7, second: 9 } }
  if nested.second.first != 7 || nested.second.second != 9 { #panic("nested >>") }
  s := Slot<i32>.Full(123)
  case s {
    .Empty => { #panic("expected Full") }
    .Full(v) => {
      if v != 123 { #panic("Slot Full value") }
    }
  }

  // 3. Standalone generic function value f<T> (replaces #instance)
  f := double_it<u32>
  if f(21) != 42 { #panic("standalone f<T>") }
  if apply_u32(double_it<u32>, 11) != 22 { #panic("pass f<T>") }

  // 4. Compile-time case T (non-taken arms including #assert(false) are skipped)
  name: str = "hello"
  if hash_tag(name) != 105 { #panic("case T str") }
  if hash_tag(true) != 201 { #panic("case T bool") }
  if hash_tag<u32>(5) != 305 { #panic("case T u32") }

  // 5. Comparison disambiguation: f(a < b, c > d) and f(a < b, c > (d))
  a := 1
  b := 2
  c := 5
  d := 3
  if !(a < b && c > d) { #panic("cmp1") }
  if !check_bools(a < b, c > d) { #panic("cmp2") }
  if !check_bools(a < b, c > (d)) { #panic("cmp3") }

  // 6. std/slice
  xs: [3]i32 = [1, 2, 3]
  ys: [3]i32 = [1, 2, 3]
  zs: [3]i32 = [1, 2, 4]
  if !slice.eql<i32>(xs[..], ys[..]) { #panic("slice.eql true") }
  if slice.eql<i32>(xs[..], zs[..]) { #panic("slice.eql false") }
  if slice.find(xs[..], 2) != 1 { #panic("slice.find") }
  if !slice.contains(xs[..], 3) { #panic("slice.contains") }
  slice.reverse(xs[..])
  if xs[0] != 3 || xs[2] != 1 { #panic("slice.reverse") }

  // 7. std/collections value constructors
  nums := col.array<i32>(arena)
  col.push(&nums, 10)
  col.push(&nums, 20)
  if nums.items.len != 2 || nums.items[1] != 20 { #panic("col.array") }

  counts := col.map<str, u32>(arena)
  col.map_upsert(&counts, "alpha", 0).* += 3
  col.map_upsert(&counts, "beta", 0).* += 7
  got := col.map_get(&counts, "alpha")
  if got == nil || got.* != 3 { #panic("col.map") }

  q := col.ring<u32>(arena, 4)
  if !col.ring_push(&q, 11) || !col.ring_push(&q, 22) { #panic("col.ring push") }
  if col.ring_pop(&q) != 11 || col.ring_pop(&q) != 22 { #panic("col.ring pop") }
}

fn check_bools(x: bool, y: bool) bool {
  return x && y
}
'''

ERRORS = [
    ('dollar_t', 'fn id(x: $T) T { return x }\nfn main() {}\n', '$T generics were removed'),
    ('colon_type', 'fn mk(T: type) T { v: T\n return v }\nfn main() {}\n', '`T: type` was removed'),
    ('hash_instance', 'fn id<T>(x: T) T { return x }\nfn main() { _ = #instance(id, i32) }\n', '#instance was removed'),
    ('case_t_assert', '''
fn check<K>(x: K) u64 {
  case K {
    u64 => { return x }
    _ => { #assert(false, "custom compile-time failure") }
  }
}
fn main() { _ = check(1.5) }
''', 'custom compile-time failure'),
    ('case_t_unmatched', '''
fn check<K>(x: K) u64 {
  case K {
    u64 => { return x }
  }
}
fn main() { _ = check(true) }
''', 'compile-time case does not match'),
]

with tempfile.TemporaryDirectory(prefix='dyn-phase2-') as tmp:
    tmp_path = Path(tmp)
    app = tmp_path / 'app'
    app.mkdir()
    main_file = app / 'main.dyn'
    main_file.write_text(PROGRAM)

    for name, compiler, extra in [('debug', DYN_DEBUG, []), ('release', DYN, ['--release'])]:
        out = tmp_path / f'bin-{name}'
        res = subprocess.run([compiler, 'build', str(app), '--no-cache', '--quiet', '--output', str(out), *extra],
                             capture_output=True, text=True)
        assert res.returncode == 0, f'{name} build failed:\n{res.stderr}'
        run = subprocess.run([str(out)], capture_output=True, text=True)
        assert run.returncode == 0, f'{name} run failed ({run.returncode}):\n{run.stderr}'

    fmt = subprocess.run([DYN, 'fmt', str(main_file)], capture_output=True, text=True)
    assert fmt.returncode == 0, f'fmt failed:\n{fmt.stderr}'
    fmt_check = subprocess.run([DYN, 'fmt', '--check', str(main_file)], capture_output=True, text=True)
    assert fmt_check.returncode == 0, f'fmt not idempotent:\n{fmt_check.stderr}'

    for tag, src, expected in ERRORS:
        d = tmp_path / f'err-{tag}'
        d.mkdir()
        (d / 'main.dyn').write_text(src)
        res = subprocess.run([DYN, 'check', str(d)], capture_output=True, text=True)
        assert res.returncode != 0, f'{tag}: expected failure, got success'
        assert expected in res.stderr, f'{tag}: expected {expected!r} in:\n{res.stderr}'

print('PASS Phase 2 generics, compile-time case T, str, std/slice, std/collections')
