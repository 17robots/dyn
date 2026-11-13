#!/usr/bin/env python3
"""Spilled values get a register for a run of uses (ssa_local_splits).

A value that lives across calls further on is spilled for its whole
interval; local splitting loads it once for a run of straight-line uses
instead of at every use. The program below keeps more values alive across
calls than there are callee-saved registers, then uses them several times
between calls, inside loops with rotated headers, in phis, in a function
with defers (protected calls) and through a payload enum. Every build must
print the same as the tree emitter, and the split build must read fewer
frame slots than DYN_NO_SPLIT=1."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"

total: u64 = 0

fn note(x: u64) u64 {
  total += x
  return x ^ 5
}

struct Record { a: u64, b: u64, c: u64, d: u64, e: u64, f: u64 }

// p lives across many calls with few uses for its length, so it spills; the
// field reads in the middle use it six times in a row.
fn wide(p: *Record, k: u64) u64 {
  a := note(k)
  b := note(a + 1)
  c := note(b + 2)
  d := note(c + 3)
  e := note(d + 4)
  f := note(e + 5)
  g := note(f + 6)
  sum := p.a + p.b + p.c + p.d + p.e + p.f
  h := note(sum + a * b)
  i := note(h + c * d)
  j := note(i + e * f)
  k2 := note(j + g * a)
  return k2 + a + b + c + d + e + f + g + h + i + j + p.a
}

fn looped(values: []u64, limit: u64) u64 {
  a := note(1)
  b := note(2)
  c := note(3)
  d := note(4)
  e := note(5)
  f := note(6)
  sum: u64 = 0
  i: usize = 0
  for i < #len(values) && values[i] < limit {
    sum += values[i] * a + b
    i += 1
  }
  for j in 0..#len(values) {
    sum ^= values[j] + c + d + e + f
    if sum > 1000000 {
      sum = sum - note(sum) + a
    }
  }
  return sum + a + b + c + d + e + f
}

fn guarded(x: u64) u64 {
  defer { total += 1 }
  a := note(x)
  b := note(x + 1)
  c := note(x + 2)
  d := note(x + 3)
  e := note(x + 4)
  f := note(x + 5)
  return note(a + b) + note(c + d) + note(e + f) + a * b + c * d + e * f
}

fn main() {
  values: [16]u64
  for i in 0..16 {
    values[i] = #cast(u64, i) * 37 + 11
  }
  record := Record{ a: 1, b: 2, c: 3, d: 4, e: 5, f: 6 }
  io.println("{} {} {} {}", wide(&record, 8), looped(values[..], 400), guarded(9), total)
}
'''
if not shutil.which('objdump'):
    print('SKIP local splits: objdump missing')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-ssa-local-splits-') as temporary:
    source = Path(temporary) / 'main.dyn'
    source.write_text(SOURCE)
    outputs, loads = {}, {}
    for name, env in (('tree', {'DYN_NO_SSA': '1'}), ('split', {}), ('nosplit', {'DYN_NO_SPLIT': '1'})):
        program = Path(temporary) / name
        subprocess.run([DYN, 'build', str(source), '--release', '--no-cache', '--quiet', '--output', str(program)],
                       check=True, timeout=120, env={**os.environ, 'DYN_NO_INLINE': '1', **env})
        result = subprocess.run([str(program)], capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, (name, result)
        outputs[name] = result.stdout
        listing = subprocess.run(['objdump', '-d', '--no-show-raw-insn', str(program)], capture_output=True,
                                 text=True, check=True).stdout
        count = 0
        for function in ('wide', 'looped', 'guarded'):
            body = re.search(rf'<{function}>:\n(.*?)\n\n', listing, re.S).group(1)
            count += len(re.findall(r'\tmov\s+-0x[0-9a-f]+\(%rbp\),%\w+', body))
        loads[name] = count
    assert outputs['split'] == outputs['tree'] == outputs['nosplit'], outputs
    assert loads['split'] < loads['nosplit'], loads
    # AArch64 and RISC-V keep more callee-saved registers, so this program
    # spills less there; their builds must still agree.
    for target, emulator in (('aarch64-linux', 'qemu-aarch64'), ('riscv64-linux', 'qemu-riscv64')):
        if not shutil.which(emulator):
            continue
        for name, env in (('split', {}), ('nosplit', {'DYN_NO_SPLIT': '1'})):
            program = Path(temporary) / f'{target}-{name}'
            subprocess.run([DYN, 'build', str(source), '--release', '--target', target, '--no-cache', '--quiet',
                            '--output', str(program)], check=True, timeout=120,
                           env={**os.environ, 'DYN_NO_INLINE': '1', **env})
            result = subprocess.run([emulator, str(program)], capture_output=True, text=True, timeout=60)
            assert result.returncode == 0 and result.stdout == outputs['tree'], (target, name, result)
print(f"PASS local splits: same output on x86-64, AArch64 and RISC-V; x86-64 frame loads {loads['nosplit']} to {loads['split']}")
