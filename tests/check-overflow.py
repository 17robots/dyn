#!/usr/bin/env python3
"""Debug builds check overflow by default: the program's own + - * << and
negation panic on overflow, std code keeps wrapping, math.wrapping_* never
checks, --no-check-overflow wraps, and release builds reject --check-overflow."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    print('SKIP check overflow: Linux x86-64 execution')
    raise SystemExit(0)
SOURCE = '''use "std/container/map"
use "std/io"
use "std/math"
use "std/mem"
use "std/process"

fn bump(x: i32) i32 {
  return x + 1
}

fn main() {
  program := process.start()
  arena := mem.arena_create(0)
  m: map.Map(u64, u64)
  map.init(&m, arena)
  map.insert(&m, 18446744073709551615, 7)
  io.println("std {}", map.get(&m, 18446744073709551615).*)
  high: u32 = 0x80000000
  io.println("wrapping {}", math.wrapping_mul(high, 2))
  mode := #len(program.args)
  if mode == 2 {
    small: u8 = 200
    small += 100
    io.println("{}", small)
  }
  if mode == 3 {
    shift: u32 = 0x80000000
    io.println("{}", shift << 1)
  }
  if mode == 4 {
    low: i32 = -2147483648
    io.println("{}", -low)
  }
  io.println("bump {}", bump(2147483647))
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-check-overflow-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE)
    for checked, flags in ((True, []), (True, ['--check-overflow']), (False, ['--no-check-overflow']),
                           (False, ['--release'])):
        output = work / ('checked' if checked else 'plain')
        built = subprocess.run([DYN, 'build', *flags, '--no-cache', str(work), '--output', str(output)],
                               capture_output=True, text=True, timeout=120)
        assert built.returncode == 0, built.stderr
        for arguments, line in (([], 8), (['a'], 23), (['a', 'b'], 28), (['a', 'b', 'c'], 32)):
            result = subprocess.run([str(output), *arguments], capture_output=True, text=True, timeout=30)
            assert result.stdout.startswith('std 7\nwrapping 0\n'), result
            if checked:
                assert result.returncode == 101, result
                assert f'runtime check failed (overflow.ok)' in result.stderr, result.stderr
                assert f'main.dyn:{line}\n' in result.stderr, (line, result.stderr)
            else:
                assert result.returncode == 0 and result.stdout.endswith('bump -2147483648\n'), result
    rejected = subprocess.run([DYN, 'build', '--release', '--check-overflow', str(work), '--output', str(work / 'r')],
                              capture_output=True, text=True, timeout=60)
    assert rejected.returncode == 2 and '--check-overflow is for debug builds' in rejected.stderr, rejected.stderr
print('PASS overflow checks: debug default checks own arithmetic, std and wrapping_* wrap, opt-out and release wrap')
