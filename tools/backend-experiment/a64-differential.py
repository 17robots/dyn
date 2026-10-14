#!/usr/bin/env python3
"""Differential AArch64 Linux check: native emission against LLVM under qemu.

Builds the value corpus from test.py (minus libc-dependent functions) into one
program per backend. Each case runs in its own qemu process, selected by its
command-line index, so panics are compared exactly: status, stdout and stderr.
"""
import argparse
import os
from pathlib import Path
import random
import re
import shutil
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
fn small_sum(s: Small) u64 { return #cast(u64) s.a + #cast(u64) s.b + #cast(u64) s.c }
pub fn agg_small(a: u8, b: u16, c: u32) u64 { return small_sum(small_make(a, b, c)) }
fn pair_swap(p: Pair) Pair { return Pair{ x: p.y, y: p.x } }
pub fn agg_pair(a: i64, b: i64) i64 { q := pair_swap(Pair{ x: a, y: b }) return #wrap(q.x * 3 - q.y) }
fn floats_scale(f: Floats, k: f32) Floats { return Floats{ x: f.x * k, y: f.y + k } }
pub fn agg_floats(a: f32, b: f32) f32 { r := floats_scale(Floats{ x: a, y: b }, 2.0) return r.x - r.y }
fn doubles_rotate(d: Doubles) Doubles { return Doubles{ a: d.c, b: d.a, c: d.b } }
pub fn agg_doubles(a: f64, b: f64) f64 { r := doubles_rotate(Doubles{ a: a, b: b, c: 1.5 }) return r.a * 100.0 + r.b * 10.0 + r.c }
fn mixed_echo(m: Mixed) Mixed { return Mixed{ f: m.f * 2.0, n: m.n + 1 } }
pub fn agg_mixed(a: f64, b: i32) f64 { r := mixed_echo(Mixed{ f: a, n: b }) return r.f + #cast(f64) r.n }
fn large_bump(l: Large) Large { m := l m.a += 1 m.e = 7 return m }
fn large_mutate(l: Large) u64 { m := l m.b = 0 return m.a + m.b }
pub fn agg_large(a: u64, b: u64) u64 { l := Large{ a: a % 1000, b: b % 1000, c: 3, d: 4, e: 5 } r := large_bump(l) _ = large_mutate(l) return r.a + l.b + #cast(u64) r.e + l.a }
fn many_structs(a: Pair, b: Floats, c: Large, d: Pair, e: Doubles, f: Small, g: Pair, h: Pair, i: Pair) i64 {
  extra := #cast(i64) (b.x + #cast(f32) e.c)
  return a.x + d.y + g.x + h.y + i.x + #cast(i64) c.a + #cast(i64) f.c + extra
}
pub fn agg_pressure(a: i64, b: i64) i64 {
  p := Pair{ x: a % 100, y: b % 100 }
  return many_structs(p, Floats{ x: 1.0, y: 2.0 }, Large{ a: 9, b: 0, c: 0, d: 0, e: 0 }, p, Doubles{ a: 0.0, b: 0.0, c: 4.0 }, Small{ a: 1, b: 2, c: 3 }, p, p, p)
}
fn array_sum(values: [5]u32) u64 { total: u64 = 0 for v in values { total += #cast(u64) v } return total }
fn array_make(seed: u32) [5]u32 { return [seed, seed + 1, seed + 2, seed + 3, seed % 7] }
pub fn agg_array(a: u32) u64 { return array_sum(array_make(a % 1000)) }
pub fn agg_slice(a: u64, b: u64) u64 {
  data: [16]u64 = []
  for i in 0..16 { data[i] = #cast(u64) i * 3 }
  s := data[a % 8..8 + b % 8]
  total: u64 = 0
  for p in s { total += p }
  return total + #cast(u64) #len(s)
}
pub fn agg_index(a: u64) u64 { data: [4]u64 = [10, 20, 30, 40] return data[a] }
pub fn agg_string(a: u64) u64 { text := "hello, native arm" part := text[a % 5..] return #cast(u64) part[0] + #cast(u64) #len(part) }
fn shape_area(s: Shape) i64 {
  case s {
    Shape.Square side => { return side * side },
    Shape.Point p => { return p.x + p.y },
    Shape.Circle r => { return #cast(i64) (r * 3.0) },
    _ => { return -1 },
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
    is i64 n => { return #cast(u64) (n % 100) + 1000 },
    is f64 n => { _ = n return 2000 },
    is Pair p => { return #cast(u64) (p.x % 10) + 3000 },
    _ => { return 9 },
  }
}
pub fn agg_any(a: i64, b: u64) u64 {
  k := b % 3
  if k == 0 { return any_kind(a) }
  if k == 1 { return any_kind(1.5) }
  return any_kind(Pair{ x: a, y: 0 })
}
fn sum_all(base: u64, values: ...u64) u64 { total := base for v in values { total += v } return total }
pub fn agg_variadic(a: u64, b: u64) u64 { return sum_all(a % 100, b % 100, 1, 2, 3) + sum_all(5) }
counter: u64 = 0
fn bump(n: u64) { counter += n }
fn deferred(a: u64, b: u64) u64 {
  defer bump(100)
  defer { counter += 10 }
  if a == 0 { return 1 }
  return a / b
}
pub fn agg_defer(a: u64, b: u64) u64 { counter = 0 r := deferred(a % 5, b % 3) return r * 1000 + counter }
pub fn agg_defer_locals(a: u64, b: u64) u64 {
  x := a % 1000 y := b % 1000 z := x * 3 w := y * 5 v := x + y u := z + w t := v * 2
  defer bump(1)
  bump(2)
  return x + y + z + w + v + u + t
}
table: [4]u64 = [1, 2, 3, 4]
computed: u64 = table[2] * 10
pub fn agg_globals(a: u64) u64 { table[a % 4] += a % 100 return table[0] + table[3] + computed }
fn apply_pair(f: *fn(Pair) Pair, p: Pair) Pair { return f(p) }
pub fn agg_indirect(a: i64, b: i64) i64 { r := apply_pair(&pair_swap, Pair{ x: a, y: b }) return #wrap(r.x - r.y) }
fn large_echo(l: Large) Large { return l }
pub fn agg_large_indirect(a: u64) u64 { f := &large_echo r := f(Large{ a: a % 1000, b: 2, c: 3, d: 4, e: 5 }) return r.a + r.d }
fn floats_echo(f: Floats) Floats { return f }
pub fn agg_hfa_indirect(a: f32) f32 { g := &floats_echo r := g(Floats{ x: a, y: 1.0 }) return r.x + r.y }
pub fn agg_pointer(a: u64) u64 { p := Pair{ x: 1, y: 2 } q := &p q.y = #cast(i64) (a % 100) r := q return #cast(u64) (r.x + r.y) }
pub fn agg_nested_loops(a: u64) u64 {
  total: u64 = 0
  outer: for i in 0..(a % 10) {
    for j in #reverse(0..=(a % 7)) { if j == 3 { continue:outer } if i * j > 20 { break:outer } total += i * 7 + j }
  }
  return total
}
"""

# C provider compiled by clang for AAPCS64 interop: struct classes, HFAs,
# indirect large structs, stack overflow arguments and callbacks into Dyn.
PROVIDER = r"""
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
extern fn c_callback(f: *fn(Pair, i64) i64, a: i64) i64
extern fn c_hfa_callback(f: *fn(Floats) Floats, a: f32) f64
extern fn c_large_callback(f: *fn(Large) Large, a: u64) u64
fn dyn_pair_callback(p: Pair, k: i64) i64 { return p.x % 1000 * k + p.y }
fn dyn_floats_callback(f: Floats) Floats { return Floats{ x: f.y, y: f.x } }
fn dyn_large_callback(l: Large) Large { m := l m.a = l.a % 1000 + l.d m.e = 9 return m }
pub fn c_abi_small(a: u8, b: u16) u64 { r := c_small(Small{ a: a % 200, b: b % 1000, c: 7 }) return #cast(u64) r.a + #cast(u64) r.b + #cast(u64) r.c }
pub fn c_abi_pair(a: i64, b: i64) i64 { r := c_pair(Pair{ x: a % 1000, y: b % 1000 }, 3) return r.x * 7 + r.y }
pub fn c_abi_floats(a: f32, b: f32) f32 { r := c_floats(Floats{ x: a, y: b }) return r.x - r.y }
pub fn c_abi_doubles(a: f64, b: f64) f64 { r := c_doubles(Doubles{ a: a, b: b, c: 0.25 }, 2.0) return r.a + r.b * 10.0 + r.c * 100.0 }
pub fn c_abi_mixed(a: f64, b: i32) f64 { r := c_mixed(Mixed{ f: a, n: b % 1000 }) return r.f + #cast(f64) r.n }
pub fn c_abi_large(a: u64, b: u64) u64 { l := Large{ a: a % 1000, b: b % 1000, c: 3, d: 4, e: 5 } r := c_large(l) m := c_large_mutates(l) return r.a + r.d + #cast(u64) r.e + l.a + m }
pub fn c_abi_spill(a: i64, b: i64) i64 { return c_spill(1, 2, 3, 4, 5, 6, a % 100, Pair{ x: b % 100, y: 2 }, 3) }
pub fn c_abi_fp_spill(a: f64) f64 { return c_fp_spill(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, a, Doubles{ a: 0.5, b: 0.25, c: 0.125 }, 9.0) }
pub fn c_abi_callback(a: i64) i64 { return c_callback(&dyn_pair_callback, a % 1000) }
pub fn c_abi_hfa_callback(a: f32) f64 { return c_hfa_callback(&dyn_floats_callback, a) }
pub fn c_abi_large_callback(a: u64) u64 { return c_large_callback(&dyn_large_callback, a) }
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
            combos.add(tuple(rng.choice(pool) for pool in pools))
            if len(combos) >= per_function: break
        if not types: combos = {()}
        for combo in sorted(combos, key=str):
            locals_ = ' '.join(f'v{k}: {t} = {v}' for k, (t, v) in enumerate(zip(types, combo)))
            call = f'{name}(' + ', '.join(f'v{k}' for k in range(len(types))) + ')'
            body = f'_ = io.println(io.stdout(), "{{}}", {call})' if result else f'{call} _ = io.println(io.stdout(), "void")'
            cases.append(f'{locals_} {body}')
    arms = '\n'.join(f'    {i} => {{ {case} }},' for i, case in enumerate(cases))
    program = f'''use "std/io"
use "std/mem"
use "std/process"
use "std/strings"
{source}
fn main() {{
  backing: [65536]u8 = []
  arena := mem.arena_from_buffer(backing[..])
  arguments := process.arguments(&arena)
  if !arguments.ok || #len(arguments.values) < 2 {{ #panic("case index required") }}
  index: u64 = 0
  if !strings.parse_u64(arguments.values[1], &index) {{ #panic("bad case index") }}
  case index {{
{arms}
    _ => {{ #panic("unknown case") }},
  }}
}}
'''
    return program, len(cases)

def no_core_dumps():
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--compiler', type=Path, default=ROOT/'build/dyn')
    parser.add_argument('--per-function', type=int, default=8)
    parser.add_argument('--seed', type=int, default=1)
    parser.add_argument('--jobs', type=int, default=os.cpu_count() or 4)
    args = parser.parse_args()
    if not shutil.which('qemu-aarch64'):
        print('SKIP AArch64 differential: qemu-aarch64 not installed'); return
    rng = random.Random(args.seed)
    program, count = build_program(rng, args.per_function)
    with tempfile.TemporaryDirectory(prefix='dyn-a64-diff-') as directory:
        root = Path(directory); (root/'app').mkdir()
        (root/'app/main.dyn').write_text(program)
        (root/'provider.c').write_text(PROVIDER)
        provider = root/'provider.o'
        clang = shutil.which('clang')
        if not clang: print('SKIP AArch64 differential: clang not installed'); return
        subprocess.run([clang, '--target=aarch64-linux-gnu', '-ffreestanding', '-fno-stack-protector', '-O1',
                        '-c', str(root/'provider.c'), '-o', str(provider)], check=True)
        outputs = {}
        for backend in ('native', 'llvm'):
            output = root/f'{backend}'
            built = subprocess.run([str(args.compiler), 'build', str(root/'app'), '--target', 'aarch64-linux',
                                    '--backend', backend, '--no-cache', '--quiet', '--link', str(provider),
                                    '--output', str(output)],
                                   capture_output=True, text=True, timeout=600)
            if built.returncode:
                (Path(tempfile.gettempdir())/'dyn-a64-diff-main.dyn').write_text(program)
                sys.exit(f'{backend} build failed:\n{built.stderr[-4000:]}')
            outputs[backend] = output
        def run(binary, index):
            try:
                r = subprocess.run(['qemu-aarch64', str(binary), str(index)], capture_output=True, timeout=5,
                                   cwd=directory, preexec_fn=no_core_dumps)
            except subprocess.TimeoutExpired:
                return 'timeout', b'', b''  # e.g. loop_forever(2^64-1) on both backends
            return r.returncode, r.stdout, r.stderr
        with ThreadPoolExecutor(args.jobs) as pool:
            native = list(pool.map(lambda i: run(outputs['native'], i), range(count)))
            llvm = list(pool.map(lambda i: run(outputs['llvm'], i), range(count)))
        dwarfdump = shutil.which('llvm-dwarfdump')
        if dwarfdump:
            verify = subprocess.run([dwarfdump, '--verify', str(outputs['native'])], capture_output=True, text=True)
            assert verify.returncode == 0 and 'No errors.' in verify.stdout, verify.stdout[-2000:]
            frames = subprocess.run([dwarfdump, '--debug-frame', str(outputs['native'])], capture_output=True, text=True)
            assert frames.returncode == 0 and 'error' not in frames.stdout + frames.stderr, (frames.stdout + frames.stderr)[-2000:]
        failures = [i for i in range(count) if native[i] != llvm[i]]
        panics = sum(1 for r in llvm if r[0] == 101)
        for i in failures[:20]:
            print(f'MISMATCH case {i}: native={native[i]} llvm={llvm[i]}')
        if failures:
            (Path(tempfile.gettempdir())/'dyn-a64-diff-main.dyn').write_text(program)
            sys.exit(f'{len(failures)} of {count} AArch64 cases differ (program saved to /tmp/dyn-a64-diff-main.dyn)')
        print(f'PASS AArch64 native/LLVM differential: {count} cases ({panics} panics) under qemu')

if __name__ == '__main__':
    main()
