#!/usr/bin/env python3
"""SSA code generation matches the tree emitter.

Division by constants uses shifts or reciprocal multiplication; every result
must equal the hardware division by the same divisor read at run time. The
programs also run with DYN_NO_SSA=1, which selects the tree emitter.
"""
import os
from pathlib import Path
import random
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
    print(f'PASS SSA division by {len(CONSTANTS)} constants at 64 and 32 bits against hardware division')


if __name__ == '__main__':
    main()
