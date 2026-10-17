#!/usr/bin/env python3
"""SSA code generation matches the tree emitter.

Division by constants uses shifts or reciprocal multiplication; every result
must equal the hardware division by the same divisor read at run time. The
programs also run with DYN_NO_SSA=1, which selects the tree emitter.
"""
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
CONSTANTS = [2, 3, 5, 6, 7, 9, 10, 12, 25, 100, 125, 641, 1000, 1000003, 65535, 65536, 2147483647,
             2147483648, 4294967295, 4294967296, 6700417, 7 ** 7, (1 << 62) + 1, (1 << 63) - 1,
             (1 << 63) + 3, (1 << 64) - 2, (1 << 64) - 1]


def division_program():
    lines = ['values: [64]u64', 'signed_divisor: i64', 'unsigned_divisor: u64', 'fn unsigned(x: u64) {']
    for c in CONSTANTS:
        lines += [f'  unsigned_divisor = {c}',
                  f'  if x / {c} != x / unsigned_divisor || x % {c} != x % unsigned_divisor {{ #panic("u64 {c}") }}']
    lines += ['}', 'fn signed(x: i64) {']
    for c in CONSTANTS:
        if c < 1 << 63:
            lines += [f'  signed_divisor = {c}',
                      f'  if x / {c} != x / signed_divisor || x % {c} != x % signed_divisor {{ #panic("i64 {c}") }}']
    lines += ['}', 'fn runtime(c: i64) i64 { signed_divisor = c return signed_divisor }', 'fn narrow(x: i32, y: u32) {']
    for c in (3, 7, 10, 1000, 65537, 2147483647):
        lines += [f'  if x / {c} != x / #cast(i32) runtime({c}) || x % {c} != x % #cast(i32) runtime({c}) {{ #panic("i32 {c}") }}',
                  f'  if y / {c} != y / #cast(u32) runtime({c}) || y % {c} != y % #cast(u32) runtime({c}) {{ #panic("u32 {c}") }}']
    rng = random.Random(5)
    values = [0, 1, 2, 3, 5, 7, (1 << 63) - 1, 1 << 63, (1 << 64) - 1, (1 << 64) - 2, (1 << 32) - 1, 1 << 32,
              999999, 1000003, 1000002] + [rng.getrandbits(64) for _ in range(40)] + [rng.getrandbits(20) for _ in range(9)]
    lines += ['}', 'fn main() {']
    lines += [f'  values[{i}] = {v}' for i, v in enumerate(values[:64])]
    lines += ['  for v in values {', '    unsigned(v)', '    signed(#bitcast(i64) v)',
              '    narrow(#cast(i32) (#bitcast(i64) v % 2147483647), #cast(u32) (v % 4294967295))', '  }', '}']
    return '\n'.join(lines) + '\n'


# Programs printing values the SSA and tree emitters must agree on, on every
# target this host can run.
PROGRAMS = {
    'wide-memory': '''use "std/io"
big: i64 = -7234210387
small: i32 = -5
bytes: [4]i8 = [-1, 2, -3, 4]
halves: [2]i16 = [-30000, 30000]
fn main() {
  _ = io.println(io.stdout(), "{} {} {} {} {}", big, small, bytes[0] + bytes[2], halves[0], #cast(u64) (-(big + 1)))
}
''',
    'jump-tables': '''use "std/io"
enum Key { Up, Down, Left, Right, Enter, Escape, Tab }
fn pick(x: i64) i64 {
  case x {
    0 => { return 10 },
    1 => { return 11 },
    2, 3 => { return 23 },
    5 => { return 15 },
    -1 => { return 99 },
    7 => { return 17 },
    _ => { return -5 }
  }
}
fn letter(x: u8) u64 {
  case x {
    65 => { return 1 },
    66 => { return 2 },
    67 => { return 3 },
    70 => { return 4 },
    _ => { return 0 }
  }
}
fn key(k: Key) i64 {
  case k {
    Key.Up => { return 1 },
    Key.Down => { return 2 },
    Key.Left => { return 3 },
    Key.Right => { return 4 },
    Key.Enter => { return 5 },
    _ => { return 6 }
  }
}
fn main() {
  total: i64 = 0
  for i in -3..12 { total = total * 7 + pick(#cast(i64) i) }
  for c in 60..75 { total += #cast(i64) letter(#cast(u8) c) * #cast(i64) c }
  total += key(Key.Up) + key(Key.Enter) * 10 + key(Key.Tab) * 100
  _ = io.println(io.stdout(), "{}", total)
}
''',
    'stack-arguments': '''use "std/io"
struct Pair { a: i64, b: f64 }
struct Wide { a: i64, b: i64, c: i64 }
fn many(a: i64, b: i8, c: i64, d: u16, e: i64, f: i32, g: i64, h: u8, i: i64, j: i8, k: f32, l: f64, m: Pair, n: Wide) f64 {
  return #cast(f64) (a + #cast(i64) b + c + #cast(i64) d + e + #cast(i64) f + g + #cast(i64) h + i + #cast(i64) j) + #cast(f64) k + l + m.b + #cast(f64) (m.a + n.a + n.b + n.c)
}
fn floats(a: f64, b: f64, c: f64, d: f64, e: f64, f: f64, g: f64, h: f64, i: f32, j: f64, k: f32) f64 {
  return a + b * 2.0 + c * 3.0 + d * 4.0 + e * 5.0 + f * 6.0 + g * 7.0 + h * 8.0 + #cast(f64) i * 9.0 + j * 10.0 + #cast(f64) k * 11.0
}
fn main() {
  x := many(1, -2, 3, 4, 5, -6, 7, 8, 9, -10, 1.5, 2.25, Pair{a: 11, b: 0.5}, Wide{a: 12, b: 13, c: 14})
  y := floats(1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.5, 10.0, 11.5)
  _ = io.println(io.stdout(), "{} {}", #cast(i64) (x * 4.0), #cast(i64) (y * 2.0))
}
''',
}


def run_programs(work):
    targets = [('x86_64-linux', [])]
    if shutil.which('qemu-aarch64'):
        targets.append(('aarch64-linux', ['qemu-aarch64']))
    if shutil.which('qemu-riscv64'):
        targets.append(('riscv64-linux', ['qemu-riscv64']))
    for name, source in PROGRAMS.items():
        directory = work/name
        directory.mkdir()
        (directory/'main.dyn').write_text(source)
        outputs = {}
        for target, runner in targets:
            for mode, environment in (('ssa', {}), ('tree', {'DYN_NO_SSA': '1'})):
                output = directory/f'{target}-{mode}'
                subprocess.run([DYN, 'build', directory, '--release', '--no-cache', '--quiet', '--target', target,
                                '--output', output], check=True, timeout=300, env=dict(os.environ, **environment))
                result = subprocess.run([*runner, output], capture_output=True, text=True, timeout=60, cwd=directory)
                outputs[(target, mode)] = (result.returncode, result.stdout)
        assert len(set(outputs.values())) == 1, (name, outputs)
    return len(targets)


def main():
    with tempfile.TemporaryDirectory(prefix='dyn-ssa-') as directory:
        work = Path(directory)
        (work/'main.dyn').write_text(division_program())
        for name, environment in (('ssa', {}), ('tree', {'DYN_NO_SSA': '1'})):
            output = work/name
            subprocess.run([DYN, 'build', work, '--release', '--no-cache', '--quiet', '--output', output],
                           check=True, timeout=300, env=dict(os.environ, **environment))
            result = subprocess.run([output], capture_output=True, text=True, timeout=60)
            assert result.returncode == 0, (name, result.stderr)
        targets = run_programs(work)
    print(f'PASS SSA division by {len(CONSTANTS)} constants against hardware division; '
          f'{len(PROGRAMS)} programs match the tree emitter on {targets} targets')


if __name__ == '__main__':
    main()
