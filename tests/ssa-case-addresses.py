#!/usr/bin/env python3
"""A local whose address is taken only inside a case arm stays in SSA code.

The scan for address-taken locals skipped case arms, so taking `&wide` in an
arm sent the whole function to the tree emitter; std's number parsing
(strings.parse_into) was one. Integer, enum and `any` cases must compile to
SSA on every 64-bit Linux backend and give the same results as the tree
emitter (DYN_NO_SSA=1)."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"

enum Shape { Dot, Line, Square }

fn fill(out: *i64, value: i64) bool {
  out.* = value
  return true
}

fn by_number(n: i64) i64 {
  wide: i64
  case n {
    1 => {
      _ = fill(&wide, 10)
      return wide + n
    }
    2, 3 => {
      ok := fill(&wide, 20)
      if ok {
        return wide * n
      }
      return -1
    }
    _ => {
      return 0
    }
  }
}

fn by_shape(shape: Shape) i64 {
  total: i64 = 1
  case shape {
    Shape.Dot => {
      _ = fill(&total, 3)
    }
    Shape.Line => {
      _ = fill(&total, total + 4)
    }
    _ => {
      total = 9
    }
  }
  return total
}

fn by_type(target: any) bool {
  wide: i64
  case target {
    *i32 p => {
      ok := fill(&wide, 70000)
      p.* = #cast(i32, wide)
      return ok
    }
    *u8 p => {
      ok := fill(&wide, 200)
      p.* = #cast(u8, wide)
      return ok
    }
    _ => {
      return false
    }
  }
}

fn main() {
  small: u8 = 0
  medium: i32 = 0
  _ = by_type(&small)
  _ = by_type(&medium)
  io.println("{} {} {} {}", by_number(1), by_number(2), by_number(3), by_number(9))
  io.println("{} {} {}", by_shape(Shape.Dot), by_shape(Shape.Line), by_shape(Shape.Square))
  io.println("{} {}", small, medium)
}
'''
EXPECTED = '11 40 60 0\n3 5 9\n200 70000\n'
FUNCTIONS = ('by_number', 'by_shape', 'by_type')
with tempfile.TemporaryDirectory(prefix='dyn-ssa-case-addresses-') as temporary:
    source = Path(temporary) / 'main.dyn'
    source.write_text(SOURCE)
    for name, flags, emulator in (('x86', [], []),
                                  ('arm', ['--target', 'aarch64-linux'], ['qemu-aarch64']),
                                  ('riscv', ['--target', 'riscv64-linux'], ['qemu-riscv64'])):
        for ssa in (True, False):
            program = Path(temporary) / f'{name}-{ssa}'
            env = {**os.environ, 'DYN_NO_INLINE': '1', **({} if ssa else {'DYN_NO_SSA': '1'})}
            built = subprocess.run([DYN, 'build', str(source), '--release', '--opt-remarks', *flags, '--no-cache',
                                    '--output', str(program)], capture_output=True, text=True, timeout=120, env=env)
            assert built.returncode == 0, (name, built.stderr)
            if ssa:
                for function in FUNCTIONS:
                    line = [l for l in built.stderr.splitlines() if l.startswith(f'remark: {function}: ')
                            and ('SSA code generation' in l or 'tree emitter' in l)]
                    assert line and 'SSA code generation' in line[0], (name, function, line)
            if emulator and not shutil.which(emulator[0]):
                continue
            result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60)
            assert result.returncode == 0 and result.stdout == EXPECTED, (name, ssa, result)
print('PASS case arms that take addresses compile to SSA and match the tree emitter')
