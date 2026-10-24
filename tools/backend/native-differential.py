#!/usr/bin/env python3
"""Differential check of a cross target against x86-64 Linux native output.

Builds the value corpus from test.py (minus libc-dependent functions) into one
program for the target and one for x86-64 Linux, the reference. Each case runs
in its own process, selected by its command-line index, so panics are compared
exactly: status, stdout and stderr.

Targets run under qemu-aarch64 (aarch64-linux), wine (x86_64-windows) or
directly on a matching host (aarch64-macos needs an Apple silicon Mac).
"""
import platform
import argparse
import base64
import json
import os
from pathlib import Path
import random
import re
import shutil
import shlex
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent

def corpus():
    text = (HERE/'test.py').read_text()
    prefix = text[:text.index('\ndef run(args')]
    scope = {'__name__': 'a64_corpus', '__file__': str(HERE/'test.py')}
    exec(compile(prefix, str(HERE/'test.py'), 'exec'), scope)
    return scope['SOURCE']


# Aggregate and runtime features beyond the scalar test.py corpus. Each public
# function takes scalars and returns a scalar so the harness can print it.
EXTRA = """
struct Small { a: u8, b: u16, c: u32 }
struct Pair { x: i64, y: i64 }
struct Floats { x: f32, y: f32 }
struct Doubles { a: f64, b: f64, c: f64 }
struct Mixed { f: f64, n: i32 }
struct Large { a: u64, b: u64, c: u64, d: u64, e: u8 }
enum Shape { Circle: f64, Square: i64, Point: Pair, Empty }
fn small_make(a: u8, b: u16, c: u32) Small { return Small{ a: a, b: b, c: c } }
fn small_sum(s: Small) u64 { return #cast(u64, s.a) + #cast(u64, s.b) + #cast(u64, s.c) }
pub fn agg_small(a: u8, b: u16, c: u32) u64 { return small_sum(small_make(a, b, c)) }
fn pair_swap(p: Pair) Pair { return Pair{ x: p.y, y: p.x } }
pub fn agg_pair(a: i64, b: i64) i64 { q := pair_swap(Pair{ x: a, y: b })
return #wrap(q.x * 3 - q.y) }
fn floats_scale(f: Floats, k: f32) Floats { return Floats{ x: f.x * k, y: f.y + k } }
pub fn agg_floats(a: f32, b: f32) f32 { r := floats_scale(Floats{ x: a, y: b }, 2.0)
return r.x - r.y }
fn doubles_rotate(d: Doubles) Doubles { return Doubles{ a: d.c, b: d.a, c: d.b } }
pub fn agg_doubles(a: f64, b: f64) f64 { r := doubles_rotate(Doubles{ a: a, b: b, c: 1.5 })
return r.a * 100.0 + r.b * 10.0 + r.c }
fn mixed_echo(m: Mixed) Mixed { return Mixed{ f: m.f * 2.0, n: m.n + 1 } }
pub fn agg_mixed(a: f64, b: i32) f64 { r := mixed_echo(Mixed{ f: a, n: b })
return r.f + #cast(f64, r.n) }
fn large_bump(l: Large) Large { m := l
m.a += 1
m.e = 7
return m }
fn large_mutate(l: Large) u64 { m := l
m.b = 0
return m.a + m.b }
pub fn agg_large(a: u64, b: u64) u64 { l := Large{ a: a % 1000, b: b % 1000, c: 3, d: 4, e: 5 }
r := large_bump(l)
_ = large_mutate(l)
return r.a + l.b + #cast(u64, r.e) + l.a }
fn many_structs(a: Pair, b: Floats, c: Large, d: Pair, e: Doubles, f: Small, g: Pair, h: Pair, i: Pair) i64 {
  extra := #cast(i64, (b.x + #cast(f32, e.c)))
  return a.x + d.y + g.x + h.y + i.x + #cast(i64, c.a) + #cast(i64, f.c) + extra
}
pub fn agg_pressure(a: i64, b: i64) i64 {
  p := Pair{ x: a % 100, y: b % 100 }
  return many_structs(p, Floats{ x: 1.0, y: 2.0 }, Large{ a: 9, b: 0, c: 0, d: 0, e: 0 }, p, Doubles{ a: 0.0, b: 0.0, c: 4.0 }, Small{ a: 1, b: 2, c: 3 }, p, p, p)
}
fn array_sum(values: [5]u32) u64 { total: u64 = 0
for v in values { total += #cast(u64, v) }
return total }
fn array_make(seed: u32) [5]u32 { return [seed, seed + 1, seed + 2, seed + 3, seed % 7] }
pub fn agg_array(a: u32) u64 { return array_sum(array_make(a % 1000)) }
pub fn agg_slice(a: u64, b: u64) u64 {
  data: [16]u64 = []
  for i in 0..16 { data[i] = #cast(u64, i) * 3 }
  s := data[a % 8..8 + b % 8]
  total: u64 = 0
  for p in s { total += p }
  return total + #cast(u64, #len(s))
}
pub fn agg_index(a: u64) u64 { data: [4]u64 = [10, 20, 30, 40]
return data[a] }
pub fn agg_string(a: u64) u64 { text := "hello, native arm"
part := text[a % 5..]
return #cast(u64, part[0]) + #cast(u64, #len(part)) }
fn shape_area(s: Shape) i64 {
  case s {
    Shape.Square side => { return side * side }
    Shape.Point p => { return p.x + p.y }
    Shape.Circle r => { return #cast(i64, (r * 3.0)) }
    _ => { return -1 }
  }
}
pub fn agg_enum(a: i64, b: u64) i64 {
  k := b % 4
  if k == 0 { return shape_area(Shape.Square(a % 1000)) }
  if k == 1 { return shape_area(Shape.Point(Pair{ x: a % 50, y: 3 })) }
  if k == 2 { return shape_area(Shape.Circle(2.5)) }
  return shape_area(Shape.Empty)
}
fn any_kind(v: any) u64 {
  case v {
    is i64 n => { return #cast(u64, (n % 100)) + 1000 }
    is f64 n => { _ = n
    return 2000 }
    is Pair p => { return #cast(u64, (p.x % 10)) + 3000 }
    _ => { return 9 }
  }
}
pub fn agg_any(a: i64, b: u64) u64 {
  k := b % 3
  if k == 0 { return any_kind(a) }
  if k == 1 { return any_kind(1.5) }
  return any_kind(Pair{ x: a, y: 0 })
}
fn sum_all(base: u64, values: ...u64) u64 { total := base
for v in values { total += v }
return total }
pub fn agg_variadic(a: u64, b: u64) u64 { return sum_all(a % 100, b % 100, 1, 2, 3) + sum_all(5) }
counter: u64 = 0
fn bump(n: u64) { counter += n }
fn deferred(a: u64, b: u64) u64 {
  defer bump(100)
  defer { counter += 10 }
  if a == 0 { return 1 }
  return a / b
}
pub fn agg_defer(a: u64, b: u64) u64 { counter = 0
r := deferred(a % 5, b % 3)
return r * 1000 + counter }
pub fn agg_defer_locals(a: u64, b: u64) u64 {
  x := a % 1000
  y := b % 1000
  z := x * 3
  w := y * 5
  v := x + y
  u := z + w
  t := v * 2
  defer bump(1)
  bump(2)
  return x + y + z + w + v + u + t
}
table: [4]u64 = [1, 2, 3, 4]
computed: u64 = table[2] * 10
pub fn agg_globals(a: u64) u64 { table[a % 4] += a % 100
return table[0] + table[3] + computed }
fn apply_pair(f: fn(Pair) Pair, p: Pair) Pair { return f(p) }
pub fn agg_indirect(a: i64, b: i64) i64 { r := apply_pair(pair_swap, Pair{ x: a, y: b })
return #wrap(r.x - r.y) }
fn large_echo(l: Large) Large { return l }
pub fn agg_large_indirect(a: u64) u64 { f := large_echo
r := f(Large{ a: a % 1000, b: 2, c: 3, d: 4, e: 5 })
return r.a + r.d }
fn floats_echo(f: Floats) Floats { return f }
pub fn agg_hfa_indirect(a: f32) f32 { g := floats_echo
r := g(Floats{ x: a, y: 1.0 })
return r.x + r.y }
pub fn agg_pointer(a: u64) u64 { p := Pair{ x: 1, y: 2 }
q := &p
q.y = #cast(i64, (a % 100))
r := q
return #cast(u64, (r.x + r.y)) }
pub fn agg_nested_loops(a: u64) u64 {
  total: u64 = 0
  outer: for i in 0..(a % 10) {
    for j in #reverse(0..=(a % 7)) { if j == 3 { continue:outer }
    if i * j > 20 { break:outer }
    total += i * 7 + j }
  }
  return total
}
"""

# C provider compiled by clang for C interop: struct classes, HFAs, indirect
# large structs, stack overflow arguments and callbacks into Dyn.
PROVIDER = r"""
#include <stdarg.h>
#include <stdint.h>
typedef struct { uint8_t a; uint16_t b; uint32_t c; } Small;
typedef struct { int64_t x, y; } Pair;
typedef struct { float x, y; } Floats;
typedef struct { double a, b, c; } Doubles;
typedef struct { double f; int32_t n; } Mixed;
typedef struct { uint64_t a, b, c, d; uint8_t e; } Large;
Small c_small(Small s) { s.a += 1; s.b *= 2; s.c ^= 0x55; return s; }
Pair c_pair(Pair p, int64_t k) { Pair r = { p.y * k, p.x - k }; return r; }
Floats c_floats(Floats f) { Floats r = { f.y * 2.0f, f.x + 0.5f }; return r; }
Doubles c_doubles(Doubles d, double k) { Doubles r = { d.c + k, d.a * k, d.b - k }; return r; }
Mixed c_mixed(Mixed m) { Mixed r = { m.f / 2.0, m.n * 3 }; return r; }
Large c_large(Large l) { l.a += l.b; l.e = (uint8_t)(l.e + 1); l.d = 0; return l; }
uint64_t c_large_mutates(Large l) { l.a = 999; return l.a + l.b; }
int64_t c_spill(int64_t a, int64_t b, int64_t c, int64_t d, int64_t e, int64_t f, int64_t g,
                Pair p, int64_t tail) { return a + b + c + d + e + f + g + p.x * 10 + p.y * 100 + tail * 1000; }
double c_fp_spill(double a, double b, double c, double d, double e, double f, double g,
                  Doubles x, double tail) { return a + b + c + d + e + f + g + x.a + x.b * 10 + x.c * 100 + tail; }
int64_t c_callback(int64_t (*f)(Pair, int64_t), int64_t a) { Pair p = { a, 2 }; return f(p, 5) + 1; }
double c_hfa_callback(Floats (*f)(Floats), float a) { Floats r = f((Floats){ a, 1.0f }); return r.x * 10 + r.y; }
uint64_t c_large_callback(Large (*f)(Large), uint64_t a) { Large r = f((Large){ a, 1, 2, 3, 4 }); return r.a + r.e; }
/* Narrow scalars after the registers run out (Apple packs them on the stack). */
int64_t c_narrow(int64_t a, int64_t b, int64_t c, int64_t d, int64_t e, int64_t f, int64_t g, int64_t h,
                 uint8_t i, int16_t j, int32_t k, uint8_t l, int64_t m) {
  return a + b + c + d + e + f + g + h + i * 10 + j * 100 + (int64_t)k * 1000 + l * 7 + m * 3;
}
double c_narrow_fp(double a, double b, double c, double d, double e, double f, double g, double h,
                   float i, double j, float k) { return a + b + c + d + e + f + g + h + i * 10 + j * 100 + k * 1000; }
int64_t c_narrow_callback(int64_t (*f)(int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t, int64_t,
                                       uint8_t, int16_t, int32_t, uint8_t, int64_t), uint8_t a) {
  return f(1, 2, 3, 4, 5, 6, 7, 8, a, -3, 70000, 200, 9) + 1;
}
int64_t c_vsum(int32_t n, ...) {
  va_list ap; va_start(ap, n); int64_t t = 0;
  for (int32_t i = 0; i < n; ++i) t += va_arg(ap, int64_t) * (i + 1);
  va_end(ap); return t;
}
double c_vmixed(int32_t n, ...) {
  va_list ap; va_start(ap, n); double t = 0;
  for (int32_t i = 0; i < n; ++i) { t += (double)va_arg(ap, int64_t); t += va_arg(ap, double) * 10; }
  va_end(ap); return t;
}
"""
INTEROP = """
extern fn c_small(s: Small) Small
extern fn c_pair(p: Pair, k: i64) Pair
extern fn c_floats(f: Floats) Floats
extern fn c_doubles(d: Doubles, k: f64) Doubles
extern fn c_mixed(m: Mixed) Mixed
extern fn c_large(l: Large) Large
extern fn c_large_mutates(l: Large) u64
extern fn c_spill(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64, p: Pair, tail: i64) i64
extern fn c_fp_spill(a: f64, b: f64, c: f64, d: f64, e: f64, f: f64, g: f64, x: Doubles, tail: f64) f64
extern fn c_callback(f: fn(Pair, i64) i64, a: i64) i64
extern fn c_hfa_callback(f: fn(Floats) Floats, a: f32) f64
extern fn c_large_callback(f: fn(Large) Large, a: u64) u64
fn dyn_pair_callback(p: Pair, k: i64) i64 { return p.x % 1000 * k + p.y }
fn dyn_floats_callback(f: Floats) Floats { return Floats{ x: f.y, y: f.x } }
fn dyn_large_callback(l: Large) Large { m := l
m.a = l.a % 1000 + l.d
m.e = 9
return m }
extern fn c_narrow(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64, h: i64, i: u8, j: i16, k: i32, l: u8, m: i64) i64
extern fn c_narrow_fp(a: f64, b: f64, c: f64, d: f64, e: f64, f: f64, g: f64, h: f64, i: f32, j: f64, k: f32) f64
extern fn c_narrow_callback(f: fn(i64, i64, i64, i64, i64, i64, i64, i64, u8, i16, i32, u8, i64) i64, a: u8) i64
extern fn c_vsum(n: i32, ...) i64
extern fn c_vmixed(n: i32, ...) f64
fn dyn_narrow(a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64, h: i64, i: u8, j: i16, k: i32, l: u8, m: i64) i64 {
  return a + b + c + d + e + f + g + h + #cast(i64, i) * 10 + #cast(i64, j) * 100 + #cast(i64, k) * 1000 + #cast(i64, l) * 7 + m * 3
}
pub fn c_abi_narrow(a: u8, b: i16) i64 { return c_narrow(1, 2, 3, 4, 5, 6, 7, 8, a, b, 70000, 200, 9) + dyn_narrow(8, 7, 6, 5, 4, 3, 2, 1, a, b, -5, 3, 1) }
pub fn c_abi_narrow_fp(a: f32) f64 { return c_narrow_fp(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, a, 0.5, 0.25) }
pub fn c_abi_narrow_callback(a: u8) i64 { return c_narrow_callback(dyn_narrow, a) }
pub fn c_abi_variadic(a: i64, b: f64) f64 { k: i64 = a % 1000
return #cast(f64, c_vsum(3, k, #cast(i64, 2), #cast(i64, 3))) + c_vmixed(2, k, b, #cast(i64, 7), 0.5) }
pub fn c_abi_small(a: u8, b: u16) u64 { r := c_small(Small{ a: a % 200, b: b % 1000, c: 7 })
return #cast(u64, r.a) + #cast(u64, r.b) + #cast(u64, r.c) }
pub fn c_abi_pair(a: i64, b: i64) i64 { r := c_pair(Pair{ x: a % 1000, y: b % 1000 }, 3)
return r.x * 7 + r.y }
pub fn c_abi_floats(a: f32, b: f32) f32 { r := c_floats(Floats{ x: a, y: b })
return r.x - r.y }
pub fn c_abi_doubles(a: f64, b: f64) f64 { r := c_doubles(Doubles{ a: a, b: b, c: 0.25 }, 2.0)
return r.a + r.b * 10.0 + r.c * 100.0 }
pub fn c_abi_mixed(a: f64, b: i32) f64 { r := c_mixed(Mixed{ f: a, n: b % 1000 })
return r.f + #cast(f64, r.n) }
pub fn c_abi_large(a: u64, b: u64) u64 { l := Large{ a: a % 1000, b: b % 1000, c: 3, d: 4, e: 5 }
r := c_large(l)
m := c_large_mutates(l)
return r.a + r.d + #cast(u64, r.e) + l.a + m }
pub fn c_abi_spill(a: i64, b: i64) i64 { return c_spill(1, 2, 3, 4, 5, 6, a % 100, Pair{ x: b % 100, y: 2 }, 3) }
pub fn c_abi_fp_spill(a: f64) f64 { return c_fp_spill(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, a, Doubles{ a: 0.5, b: 0.25, c: 0.125 }, 9.0) }
pub fn c_abi_callback(a: i64) i64 { return c_callback(dyn_pair_callback, a % 1000) }
pub fn c_abi_hfa_callback(a: f32) f64 { return c_hfa_callback(dyn_floats_callback, a) }
pub fn c_abi_large_callback(a: u64) u64 { return c_large_callback(dyn_large_callback, a) }
"""

FOREIGN = ('abs', 'llabs', 'difftime', 'malloc', 'free')
SCALARS = {'i8': (8, True), 'i16': (16, True), 'i32': (32, True), 'i64': (64, True), 'isize': (64, True),
           'u8': (8, False), 'u16': (16, False), 'u32': (32, False), 'u64': (64, False), 'usize': (64, False)}

def values(ty, rng):
    if ty == 'bool': return ['true', 'false']
    if ty in ('f32', 'f64'): return ['0.0', '1.5', '-2.25', '1000000.0', '-0.0', '3.0e10']
    bits, signed = SCALARS[ty]
    low, high = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
    picks = {0, 1, 2, 3, 5, 63, 64, high, low, high - 1}
    if signed: picks |= {-1, -2, -5, low + 1}
    picks |= {rng.randint(low, high) for _ in range(3)}
    picks |= {rng.randint(-20 if signed else 0, 20) for _ in range(3)}
    return sorted(v for v in picks if low <= v <= high)

def bounded_combo(name, types, combo):
    """Bound work, not integer coverage, for loops with input-sized execution.

    Arithmetic and ABI cases keep their full-width inputs. Range cases retain
    their starting endpoint (including integer extrema), but use nearby ending
    endpoints. These tests compare results, not architecture-specific exhaustion
    of time or stack space. Any remaining timeout is a qualification failure.
    """
    result = list(combo)
    if name in ('loop_nested', 'loop_forever', 'loop_condition_div', 'generic_recursion'):
        result[0] = str(int(result[0]) % 65)
    elif name == 'range_bound_panic':
        # Preserve a+1 overflow and divide-by-zero cases, otherwise bound work.
        if int(result[0]) != (1 << 64) - 1:
            result[0] = str(int(result[0]) % 65)
    elif re.fullmatch(r'range_(?:i64|u64)_[01]_[01]', name) or name in ('range_controls', 'range_nested'):
        bits, signed = SCALARS[types[0]]
        low = -(1 << (bits - 1)) if signed else 0
        high = (1 << (bits - int(signed))) - 1
        start = int(result[0])
        # Include empty, forward and reverse ranges near either integer limit.
        result[1] = str(max(low, min(high, start + int(result[1]) % 65 - 32)))
    return tuple(result)

def build_program(rng, per_function):
    source = corpus() + EXTRA + INTEROP

    # Drop extern declarations and any function that reaches libc.
    lines = [l for l in source.split('\n') if not l.startswith('extern fn') or l.startswith('extern fn c_')]
    source = '\n'.join(lines)
    functions = re.findall(r'pub fn (\w+)\(([^)]*)\)\s*([\w]*)\s*\{', source)
    blocked = set(FOREIGN)
    # Iterate so callers of removed functions are removed too.
    bodies = {}
    for match in re.finditer(r'pub fn (\w+)\(', source):
        start = match.start(); depth = 0; i = source.index('{', start)
        while True:
            if source[i] == '{': depth += 1
            elif source[i] == '}':
                depth -= 1
                if depth == 0: break
            i += 1
        bodies[match.group(1)] = (start, i + 1)
    changed = True
    while changed:
        changed = False
        for name, (start, end) in bodies.items():
            if name in blocked: continue
            body = source[start:end]
            if any(re.search(rf'\b{b}\b', body) for b in blocked):
                blocked.add(name); changed = True
    pieces = []; cursor = 0
    for name, (start, end) in sorted(bodies.items(), key=lambda item: item[1][0]):
        if name in blocked:
            pieces.append(source[cursor:start]); cursor = end
    pieces.append(source[cursor:])
    source = ''.join(pieces)
    cases = []
    for name, params, result in functions:
        if name in blocked or '$' in params: continue
        types = [p.split(':')[1].strip() for p in params.split(',') if p.strip()]
        if any(t not in SCALARS and t not in ('bool', 'f32', 'f64') for t in types): continue
        if result and result not in SCALARS and result not in ('bool', 'f32', 'f64'): continue
        if len(types) > 12: continue
        pools = [values(t, rng) for t in types]
        combos = set()
        for _ in range(per_function * 3):
            combos.add(bounded_combo(name, types, tuple(rng.choice(pool) for pool in pools)))
            if len(combos) >= per_function: break
        if not types: combos = {()}
        for combo in sorted(combos, key=str):
            locals_ = ' '.join(f'v{k}: {t} = {v}' for k, (t, v) in enumerate(zip(types, combo)))
            call = f'{name}(' + ', '.join(f'v{k}' for k in range(len(types))) + ')'
            body = f'_ = io.println(io.stdout(), "{{}}", {call})' if result else f'{call} _ = io.println(io.stdout(), "void")'
            cases.append(f'{locals_} {body}')
    # Keep the dispatcher below object-format function/unwind size limits while
    # retaining every generated case. Large-frame functions remain in the corpus.
    dispatchers = []
    dispatch_arms = []
    for start in range(0, len(cases), 128):
        group = start // 128
        arms = '\n'.join(f'    {i} => {{ {case} }},'
                         for i, case in enumerate(cases[start:start + 128], start))
        dispatchers.append(f'fn dispatch_{group}(index:u64) {{ case index {{\n{arms}\n'
                           '    _ => { #panic("unknown case") },\n  }\n}\n')
        dispatch_arms.append(f'    {group} => {{ dispatch_{group}(index) }},')
    dispatch_source = '\n'.join(dispatchers)
    arms = '\n'.join(dispatch_arms)
    program = f'''use "std/io"
use "std/mem"
use "std/process"
use "std/strings"
{source}
{dispatch_source}
fn main() {{
  backing: [65536]u8 = []
  arena := mem.arena_from_buffer(backing[..])
  arguments := process.arguments(&arena)
  if !arguments.ok || #len(arguments.values) < 2 {{ #panic("case index required") }}
  if !strings.valid(u64, arguments.values[1]) {{ #panic("bad case index") }}
  index := strings.parse(u64, arguments.values[1])
  case index / 128 {{
{arms}
    _ => {{ #panic("unknown case") }},
  }}
}}
'''
    return program, len(cases)

def no_core_dumps():
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

# clang target triple and the command prefix that runs a target executable.
TARGETS = {
    'x86_64-linux': 'x86_64-linux-gnu',
    'aarch64-linux': 'aarch64-linux-gnu',
    'riscv64-linux': 'riscv64-unknown-linux-gnu',
    'x86_64-windows': 'x86_64-pc-windows-msvc',
    'aarch64-macos': 'arm64-apple-macosx15.0',
    'x86_64-macos': 'x86_64-apple-macosx15.0',
    'aarch64-windows': 'aarch64-pc-windows-msvc',
}

def runner(target):
    machine = platform.machine().lower()
    if target == 'x86_64-linux':
        return [] if sys.platform.startswith('linux') and machine in ('x86_64', 'amd64') else None
    if target == 'riscv64-linux':
        if sys.platform.startswith('linux') and machine == 'riscv64': return []
        return ['qemu-riscv64'] if shutil.which('qemu-riscv64') else None
    if target == 'aarch64-linux':
        if sys.platform.startswith('linux') and machine in ('aarch64', 'arm64'): return []
        return ['qemu-aarch64'] if shutil.which('qemu-aarch64') else None
    if target == 'aarch64-windows':
        return [] if sys.platform == 'win32' and machine in ('aarch64', 'arm64') else None
    if target == 'x86_64-macos':
        return [] if sys.platform == 'darwin' and machine in ('x86_64', 'amd64') else None
    if target == 'x86_64-windows':
        if sys.platform == 'win32': return []
        wine = shutil.which('wine') or shutil.which('wine64')
        return [wine] if wine else None
    return [] if sys.platform == 'darwin' and machine == 'arm64' else None

def build(args, root, program):
    """Build the corpus for the target and for the x86-64 Linux reference."""
    (root/'app').mkdir(exist_ok=True)
    (root/'app/main.dyn').write_text(program)
    (root/'provider.c').write_text(PROVIDER)
    clang = shutil.which(os.environ.get('CLANG', 'clang'))
    if not clang: return None
    outputs = {}
    suffix = '.exe' if args.target.endswith('-windows') else ''
    for name, target in (('native', args.target), ('reference', 'x86_64-linux')):
        provider = root/f'provider-{name}.o'
        target_flags = ['-march=rv64g', '-mno-relax'] if target == 'riscv64-linux' else []
        subprocess.run([clang, f'--target={TARGETS[target]}', *target_flags, '-ffreestanding', '-fno-stack-protector', '-O1',
                        '-c', str(root/'provider.c'), '-o', str(provider)], check=True)
        output = root/(name + (suffix if name == 'native' else ''))
        built = subprocess.run([str(args.compiler), 'build', str(root/'app'), '--target', target,
                                '--no-cache', '--quiet', *(['--release'] if args.release else []),
                                '--link', str(provider), '--output', str(output)],
                               capture_output=True, text=True, timeout=600)
        if built.returncode:
            (Path(tempfile.gettempdir())/'dyn-native-diff-main.dyn').write_text(program)
            sys.exit(f'{name} build failed:\n{built.stderr[-4000:]}')
        outputs[name] = output
    dwarfdump = shutil.which('llvm-dwarfdump')
    debug_object = outputs['native'].with_name(outputs['native'].name + '.dynnative.o')
    dwarf = debug_object if args.target.endswith('-macos') else outputs['native']
    if dwarfdump and dwarf and not args.release:
        verify = subprocess.run([dwarfdump, '--verify', str(dwarf)], capture_output=True, text=True)
        assert verify.returncode == 0 and 'No errors.' in verify.stdout, verify.stdout[-2000:]
        frames = subprocess.run([dwarfdump, '--debug-frame', str(dwarf)], capture_output=True, text=True)
        assert frames.returncode == 0 and 'error' not in frames.stdout + frames.stderr, (frames.stdout + frames.stderr)[-2000:]
    return outputs

def outcome(status, stdout, stderr):
    """Fatal faults compare as 'crash' across hosts: a POSIX signal (negative
    status) or a Windows NTSTATUS error such as 0xC00000FD, stack overflow."""
    if isinstance(status, int) and (status < 0 or status >= 0xC0000000):
        return 'crash', stdout, b''
    return status, stdout, stderr

def run_cases(prefix, binary, count, directory, jobs):
    """Runs every case in its own process; returns (status, stdout, stderr) per case."""
    environment = dict(os.environ, WINEDEBUG='-all')
    def run(index):
        try:
            r = subprocess.run([*prefix, str(binary), str(index)], capture_output=True, timeout=30,
                               cwd=directory, env=environment,
                               preexec_fn=None if sys.platform == 'win32' else no_core_dumps)
        except subprocess.TimeoutExpired:
            return 'timeout', b'', b''
        # qemu reports fatal signals itself; the status already records them.
        stderr = re.sub(rb'qemu: uncaught target signal [^\n]*\n', b'', r.stderr)
        return outcome(r.returncode, r.stdout, stderr)
    if prefix and 'wine' in Path(prefix[0]).name: run(0)  # create the wine prefix once
    with ThreadPoolExecutor(jobs) as pool:
        return list(pool.map(run, range(count)))

def save_expected(path, results):
    path.write_text(json.dumps([[status, base64.b64encode(out).decode(), base64.b64encode(err).decode()]
                                for status, out, err in results]) + '\n')

def load_expected(path):
    return [(status, base64.b64decode(out), base64.b64decode(err))
            for status, out, err in json.loads(path.read_text())]

def compare(target, prefix, binary, expected, directory, jobs):
    """Runs every case on the target program against the reference results; exits on a mismatch."""
    count = len(expected)
    expected = [outcome(*result) for result in expected]
    native = run_cases(prefix, binary, count, directory, jobs)
    # Equal timeouts do not prove equal behavior either. Every case must finish.
    timed = [i for i in range(count) if 'timeout' in (native[i][0], expected[i][0])]
    failures = [i for i in range(count) if native[i] != expected[i] or i in timed]
    panics = sum(1 for r in expected if r[0] == 101)
    for i in failures[:20]:
        label = 'TIMEOUT' if i in timed else 'MISMATCH'
        print(f'{label} case {i}: {target}={native[i]} reference={expected[i]}')
    if failures:
        sys.exit(f'{len(failures)} of {count} {target} cases differ or did not finish')
    how = f'under {Path(prefix[0]).name}' if prefix else 'on the host'
    print(f'PASS {target} differential against x86-64 Linux: {count} cases ({panics} panics, no timeouts) {how}')

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', choices=sorted(TARGETS), default='aarch64-linux')
    parser.add_argument('--release', action='store_true', help='compare optimized SSA builds instead of debug builds')
    parser.add_argument('--build-only', action='store_true', help='build both programs without running them')
    parser.add_argument('--stage', type=Path, help='build both programs into this directory for another machine')
    parser.add_argument('--run', type=Path, help='run programs staged with --stage on this machine')
    parser.add_argument('--compiler', type=Path, default=ROOT/'build/dyn')
    parser.add_argument('--per-function', type=int, default=8)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--jobs', type=int, default=os.cpu_count() or 4)
    args = parser.parse_args()
    if args.run:
        staged = json.loads((args.run/'cases.json').read_text())
        prefix = runner(staged['target'])
        if prefix is None: sys.exit(f'no runner for {staged["target"]} on this machine')
        binary = args.run.resolve()/staged['program']
        if sys.platform != 'win32':  # artifact downloads drop the executable bit
            binary.chmod(binary.stat().st_mode | 0o111)
        compare(staged['target'], prefix, binary, load_expected(args.run/'expected.json'), args.run, args.jobs)
        return
    if runner('x86_64-linux') is None:
        print('SKIP differential: the x86-64 Linux reference needs an x86-64 Linux host'); return
    prefix = runner(args.target)
    if prefix is None and (args.build_only or args.stage): prefix = []
    elif prefix is None:
        print(f'SKIP {args.target} differential: no runner (qemu-aarch64, wine or a matching host)'); return
    rng = random.Random(args.seed)
    program, count = build_program(rng, args.per_function)
    if args.stage:
        if args.stage.exists(): shutil.rmtree(args.stage)
        args.stage.mkdir(parents=True)
        outputs = build(args, args.stage.resolve(), program)
        if outputs is None: sys.exit('clang is required to stage the differential')
        save_expected(args.stage/'expected.json', run_cases([], outputs['reference'], count, args.stage, args.jobs))
        outputs['reference'].unlink()
        (args.stage/'cases.json').write_text(json.dumps({'target': args.target, 'program': outputs['native'].name}) + '\n')
        print(f'STAGED {args.target} differential: {count} cases in {args.stage}')
        return
    with tempfile.TemporaryDirectory(prefix='dyn-native-diff-') as directory:
        outputs = build(args, Path(directory), program)
        if outputs is None: print(f'SKIP {args.target} differential: clang not installed'); return
        if args.build_only:
            print(f'PASS {args.target} and reference builds: {count} cases (not run)'); return
        try:
            expected = run_cases([], outputs['reference'], count, directory, args.jobs)
            compare(args.target, prefix, outputs['native'], expected, directory, args.jobs)
        except SystemExit:
            (Path(tempfile.gettempdir())/'dyn-native-diff-main.dyn').write_text(program)
            print('program saved to /tmp/dyn-native-diff-main.dyn')
            raise

if __name__ == '__main__':
    main()
