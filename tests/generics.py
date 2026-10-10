#!/usr/bin/env python3
"""Type parameters: inference, explicit type arguments, instances across
modules, diagnostics, and cache reuse when generic bodies or callers change."""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())

UTIL = '''pub struct Pair { a: i64, b: i64 }

fn helper(x: usize) usize {
  return x * 2
}

pub fn double_size($T: type) usize {
  return helper(#sizeof(T))
}

pub fn fill(items: []$T, value: T) {
  for *item in items {
    item.* = value
  }
}

pub fn largest(items: []const $T) T {
  best := items[0]
  for item in items {
    if item > best { best = item }
  }
  return best
}

pub fn min(a, b: $T) T {
  if a < b { return a }
  return b
}

pub fn swap(a, b: *$T) {
  t := a.*
  a.* = b.*
  b.* = t
}

pub fn zero(value: *$T) {
  empty: T
  value.* = empty
}

pub fn total(items: []const $T) T {
  sum: T = 0
  for item in items {
    sum += item
  }
  return sum
}

pub fn count_down(n: $T) T {
  if n == 0 { return 0 }
  return count_down(n - 1) + 1
}
'''

MAIN = '''use "std/io"
use "util"

struct Cell { ch: u32, fg: u32 }

fn main() {
  out := io.stdout()
  cells: [3]Cell = [Cell{ch: 1}, Cell{ch: 2}, Cell{ch: 3}]
  util.fill(cells[..], Cell{ch: 9, fg: 1})
  _ = io.println(out, "{} {}", cells[2].ch, cells[0].fg)
  _ = io.println(out, "{} {} {}", util.double_size(Cell), util.double_size(util.Pair), util.double_size(*Cell))
  nums: [3]i32 = [4, -2, 11]
  _ = io.println(out, "{} {}", util.largest(nums[..]), util.total(nums[..]))
  x: u32 = 7
  _ = io.println(out, "{} {}", util.min(x, 3), util.min(2.5, 1.5))
  a: i64 = 1
  b: i64 = 2
  util.swap(&a, &b)
  _ = io.println(out, "{} {}", a, b)
  util.zero(&cells[1])
  _ = io.println(out, "{} {}", cells[1].ch, util.count_down(5))
}
'''
EXPECTED = '9 1\n16 32 16\n11 13\n3 1.5\n2 1\n0 5'

STD = '''use "std/io"
use "std/mem"
use "std/math"
use "std/sort"
use "std/slice"

struct Node { value: i32, next: *Node }

fn main() {
  out := io.stdout()
  backing: [4096]u8
  arena := mem.arena_from_buffer(backing[..])
  node := mem.push(Node, &arena)
  nodes := mem.push_array(Node, &arena, 4)
  nodes[3].value = 7
  one := mem.push(i64, &arena)
  many := mem.push_array(u16, &arena, 3)
  bytes := mem.push_bytes_uninit(&arena, 8)
  mem.fill(bytes, 5)
  _ = io.println(out, "{} {} {} {} {}", node.value, nodes[3].value, one.*, many[2], bytes[7])
  xs: [4]i32 = [1, 2, 3, 4]
  _ = mem.move(xs[1..], xs[..3])
  mem.swap(&xs[0], &xs[3])
  mem.zero(nodes)
  _ = io.println(out, "{} {} {} {}", xs[0], xs[3], mem.equal(xs[1..3], xs[2..4]), nodes[3].value)
  x: u32 = 7
  _ = io.println(out, "{} {} {} {} {}", math.min(x, 3), math.max(2.5, 4.0), math.clamp(15, 0, 10), math.abs(-4), math.narrow(u8, 200))
  big: [40]i64
  for i in 0..40 { big[i] = #cast(i64) ((i * 37) % 40) - 20 }
  sort.sort(big[..])
  small: [5]f32 = [3.0, 1.0, 2.0, 5.0, 4.0]
  sort.sort(small[..])
  slice.reverse(small[..])
  _ = io.println(out, "{} {} {} {} {} {} {}", big[0], big[39], small[0], sort.search(big[..], 7).index,
    sort.search(big[..], 7).found, slice.index_of(small[..], 2.0), slice.contains(small[..], 9.0))
}
'''
STD_EXPECTED = '0 7 0 0 5\n3 1 false 0\n3 4 10 4 200\n-20 19 5 27 true 3 false'
STD_ERRORS = {
    'use of storage after arena_reset': '  b: [64]u8\n  a := mem.arena_from_buffer(b[..])\n  n := mem.push(Node, &a)\n  mem.arena_reset(&a)\n  _ = n.value',
    'in instance min(Node) required here': '  _ = math.min(Node{}, Node{})',
}

PRELUDE = '''struct Rect { w: i32 }
fn min(a, b: $T) T {
  if a < b { return a }
  return b
}
fn make($T: type) T {
  v: T
  return v
}
fn deep(x: $T) {
  deep(&x)
}
'''
ERRORS = {
    'aggregate values are not comparable': '  r := Rect{w: 1}\n  _ = min(r, r)',
    'in instance min(Rect) required here': '  r := Rect{w: 1}\n  _ = min(r, r)',
    'T is both u32 and i64 in this call': '  x: u32 = 1\n  y: i64 = 2\n  _ = min(x, y)',
    'expected a type argument': '  _ = make(3)',
    'a type is not a value': '  _ = min(Rect, 2)',
    'a generic function can only be called': '  f := &min',
    'generic instances nest too deeply': '  deep(1)',
    'function argument count mismatch': '  _ = make()',
}


def run(*args, env=None):
    return subprocess.run([DYN, *args], capture_output=True, text=True, timeout=300, env=env)


with tempfile.TemporaryDirectory(prefix='dyn-generics-') as temporary:
    root = Path(temporary)
    project = root/'project'
    (project/'util').mkdir(parents=True)
    (project/'util/util.dyn').write_text(UTIL)
    (project/'main.dyn').write_text(MAIN)
    for release in (False, True):
        output = project/('release' if release else 'debug')
        built = run('build', str(project), '--quiet', '--no-cache', '--output', str(output),
                    *(['--release'] if release else []))
        assert built.returncode == 0, built.stderr
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
        assert result.stdout.strip() == EXPECTED, (release, result.stdout, result.stderr)

    for message, body in ERRORS.items():
        case = root/'errors'
        case.mkdir(exist_ok=True)
        (case/'main.dyn').write_text(PRELUDE + 'fn main() {\n' + body + '\n}\n')
        checked = run('check', str(case))
        assert checked.returncode != 0 and message in checked.stderr, (message, checked.stderr)

    # A generic body edit changes the output; a new instance does too.
    env = dict(os.environ, DYN_CACHE_DIR=str(root/'cache'))
    output = project/'cached'
    def build_and_run():
        built = run('build', str(project), '--quiet', '--output', str(output), env=env)
        assert built.returncode == 0, built.stderr
        return subprocess.run([str(output)], capture_output=True, text=True, timeout=30).stdout.strip()
    assert build_and_run() == EXPECTED
    util = project/'util/util.dyn'
    util.write_text(UTIL.replace('return helper(#sizeof(T))', 'return helper(#sizeof(T)) + 1'))
    assert build_and_run().splitlines()[1] == '17 33 17'
    main = project/'main.dyn'
    main.write_text(MAIN.replace('util.min(2.5, 1.5)', 'util.min(#cast(i8) 2, 1)'))
    assert build_and_run().splitlines()[3] == '3 1'

    # In a module split into chunks, an instance lives in its generic's chunk.
    # A new instance or a generic body edit must not reuse a stale chunk.
    big = root/'big'
    big.mkdir()
    def filler(prefix):
        return ''.join(f'fn {prefix}_{i}(x: i64) i64 {{\n  return x + {i}\n}}\n' for i in range(400))
    (big/'part0.dyn').write_text('fn pick(a, b: $T) T {\n  return a + b\n}\n' + filler('p0'))
    for n in range(1, 8):
        (big/f'part{n}.dyn').write_text(f'fn value{n}() i64 {{\n  return {n}\n}}\n' + filler(f'p{n}'))
    (big/'part3.dyn').write_text('fn value3() i64 {\n  return pick(1, 2)\n}\n' + filler('p3'))
    (big/'main.dyn').write_text('use "std/io"\nfn main() {\n  total := ' +
                                ' + '.join(f'value{n}()' for n in range(1, 8)) +
                                '\n  _ = io.println(io.stdout(), "{}", total)\n}\n')
    def build_big():
        built = subprocess.run([DYN, 'build', str(big), '--verbose', '--output', str(big/'program')],
                               capture_output=True, text=True, timeout=300, env=env)
        assert built.returncode == 0, built.stderr
        out = subprocess.run([str(big/'program')], capture_output=True, text=True, timeout=30)
        return int(out.stdout), built.stderr.count('cached module')
    assert build_big()[0] == 28
    (big/'part5.dyn').write_text('fn value5() i64 {\n  return #cast(i64) pick(#cast(i32) 2, 3)\n}\n' + filler('p5'))
    total, cached = build_big()
    assert total == 28 and cached > 0, (total, cached)
    part0 = big/'part0.dyn'
    part0.write_text(part0.read_text().replace('return a + b', 'return a + b + 1'))
    total, cached = build_big()
    assert total == 30 and cached > 0, (total, cached)

    # Generic std helpers over integer, float, struct and slice types.
    std = root/'std-helpers'
    std.mkdir()
    (std/'main.dyn').write_text(STD)
    for release in (False, True):
        output = std/('release' if release else 'debug')
        built = run('build', str(std), '--quiet', '--no-cache', '--output', str(output),
                    *(['--release'] if release else []))
        assert built.returncode == 0, built.stderr
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
        assert result.stdout.strip() == STD_EXPECTED, (release, result.stdout, result.stderr)
    for message, body in STD_ERRORS.items():
        (std/'main.dyn').write_text('use "std/mem"\nuse "std/math"\nstruct Node { value: i32 }\nfn main() {\n' + body + '\n}\n')
        checked = run('check', str(std))
        assert checked.returncode != 0 and message in checked.stderr, (message, checked.stderr)
    (std/'main.dyn').write_text('use "std/math"\nfn main() {\n  _ = math.narrow(u8, 300)\n}\n')
    result = run('run', str(std))
    assert result.returncode != 0 and 'narrow(u8, i32)' in result.stderr, result.stderr

print('PASS generics: inference, type arguments, cross-module instances, diagnostics, cache, std helpers')
