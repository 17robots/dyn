#!/usr/bin/env python3
"""Small branches that only choose a value become selects.

ssa_selects turns a diamond or triangle whose arms hold at most two cheap,
non-trapping integer values into SO_SELECT: CMOVcc on x86-64 after the
fused comparison, CSEL on AArch64; RISC-V keeps the branch. The program
covers clamps, min/max, conditional increments, constants on either side,
and selects under register pressure (spilled destinations use scratch
registers). Every build prints what the tree emitter prints."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"

sink: u64 = 0

fn note(x: u64) u64 {
  sink += x
  return x
}

fn clamp(x: i64, low: i64, high: i64) i64 {
  r := x
  if r < low {
    r = low
  }
  if r > high {
    r = high
  }
  return r
}

fn count_ascii(text: []const u8) u64 {
  ascii: u64 = 0
  for b in text {
    if b < 128 {
      ascii += 1
    }
  }
  return ascii
}

fn pick(a: u64, b: u64, flag: bool) u64 {
  r: u64 = 0
  if flag {
    r = a + 1
  } else {
    r = b * 3
  }
  return r
}

fn constants(x: u64) u64 {
  r: u64 = 125
  if (x & 1) == 0 {
    r = 93
  }
  return r
}

// Many values live across calls, so some selects spill.
fn pressure(x: u64) u64 {
  a := note(x)
  b := note(x + 1)
  c := note(x + 2)
  d := note(x + 3)
  e := note(x + 4)
  f := note(x + 5)
  g := note(x + 6)
  p: u64 = 7
  if a > 3 {
    p = 9
  }
  q := a
  if b < c {
    q = d
  }
  r := note(p + q)
  return r + a + b + c + d + e + f + g + p + q
}

fn main() {
  total: i64 = 0
  for i: i64 in -50..50 {
    total += clamp(i * 7, -100, 120)
  }
  more: u64 = 0
  for i in 0..20 {
    more += constants(#cast(u64, i)) + pressure(#cast(u64, i))
  }
  io.println("{} {} {} {} {} {}", total, count_ascii("h\\xc3\\xa9llo w\\xc3\\xb6rld"), pick(3, 4, true), pick(3, 4, false), more, sink)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-ssa-selects-') as temporary:
    source = Path(temporary) / 'main.dyn'
    source.write_text(SOURCE)
    expected = None
    for target, emulator, disassembler in (('x86_64-linux', [], ['objdump']), ('aarch64-linux', ['qemu-aarch64'], ['llvm-objdump']),
                                           ('riscv64-linux', ['qemu-riscv64'], None), ('x86_64-windows', ['wine'], None)):
        for name, env in (('tree', {'DYN_NO_SSA': '1'}), ('ssa', {'DYN_NO_INLINE': '1'}), ('inlined', {})):
            program = Path(temporary) / f'{target}-{name}{".exe" if "windows" in target else ""}'
            subprocess.run([DYN, 'build', str(source), '--release', '--target', target, '--no-cache', '--quiet',
                            '--output', str(program)], check=True, timeout=120, env={**os.environ, **env})
            if name == 'ssa' and disassembler and shutil.which(disassembler[0]):
                listing = subprocess.run([*disassembler, '-d', '--no-show-raw-insn', str(program)], capture_output=True,
                                         text=True, check=True).stdout
                clamp = re.search(r'<clamp>:\n(.*?)\n\n', listing, re.S).group(1)
                if target == 'x86_64-linux':
                    assert len(re.findall(r'\tcmov', clamp)) == 2 and not re.search(r'\tj[a-z]+ ', clamp), clamp
                else:
                    assert len(re.findall(r'\tcsel\t', clamp)) == 2 and not re.search(r'\tb\.', clamp), clamp
            if emulator and not shutil.which(emulator[0]):
                continue
            result = subprocess.run([*emulator, str(program)], capture_output=True, text=True, timeout=60,
                                    env={**os.environ, 'WINEDEBUG': '-all'})
            assert result.returncode == 0, (target, name, result)
            output = result.stdout.replace('\r\n', '\n')
            expected = expected or output
            assert output == expected, (target, name, output, expected)
print('PASS selects: CMOV/CSEL clamps, constants, spilled selects; outputs match on every target')
