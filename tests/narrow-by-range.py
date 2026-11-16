#!/usr/bin/env python3
"""x & M with a constant M, and unsigned x >> k with a constant k, convert to
a smaller integer type without #cast when their range fits; nothing else
narrows implicitly."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"

const Mask := 0x3f

struct Out { low: u8, top: u8, mid: u16, small: i8 }

fn byte_of(x: u64, n: u64) u8 {
  return (x >> (n * 8)) & 0xff
}

fn take(value: u8) u8 {
  return value
}

fn main() {
  x: u64 = 0x1122334455667788
  a: u8 = x & 0xff
  b: u8 = x >> 56
  c: u16 = x & 0xffff
  d: u32 = x >> 32
  e: i64 = -5
  f: u8 = e & 0xff
  g: u8 = x & Mask
  h := Out{ low: x & 0xff, top: x >> 56, mid: x >> 48, small: x & 0x7f }
  a += x & 0xf
  io.println("{} {} {} {} {} {} {} {} {} {}", a, b, c, d, f, g, byte_of(x, 1), h.top, h.small, take(x >> 60))
}
'''
EXPECTED = '144 17 30600 287454020 251 8 119 17 8 1\n'
REJECTED = ('y: u8 = x & 0x1ff', 'y: u8 = x >> 8', 'y: u8 = s >> 56', 'y: u8 = x | 0xff', 'y: i8 = x & 0xff',
            'if x < 256 { y: u8 = x }', 'y: u8 = x >> 0', 'y: u8 = x & ~0xff')
with tempfile.TemporaryDirectory(prefix='dyn-narrow-by-range-') as temporary:
    work = Path(temporary)
    (work / 'ok').mkdir()
    (work / 'ok' / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        program = work / 'program'
        subprocess.run([DYN, 'build', str(work / 'ok'), mode, '--no-cache', '--quiet', '--output', str(program)],
                       check=True, timeout=180)
        output = subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30).stdout
        assert output == EXPECTED, (mode, output)
    for index, line in enumerate(REJECTED):
        bad = work / f'bad{index}'
        bad.mkdir()
        (bad / 'main.dyn').write_text(f'fn main() {{\n  x: u64 = 5\n  s: i64 = 5\n  {line}\n  _ = s\n}}\n')
        checked = subprocess.run([DYN, 'check', str(bad)], capture_output=True, text=True, timeout=60)
        assert checked.returncode != 0 and 'mismatch' in checked.stderr, (line, checked.stderr)
print('PASS narrowing by range: & constant and unsigned >> constant convert when they fit; nothing else does')
