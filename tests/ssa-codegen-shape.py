#!/usr/bin/env python3
"""Shapes of optimized x86-64 code that the benchmark kernels rely on.

- A self tail call becomes a jump: ten million nested calls run in constant
  stack, and quicksort calls itself once instead of twice.
- A loop's next value computed by a two-address chain, `at = (at + 1) &
  mask`, stays in the phi's register: no move between the ADD and the AND.
- Wide constants used in a loop live in registers, not one MOVABS per use.
- A loop whose header loads and checks before comparing is rotated: the
  latch repeats the header instead of jumping back to it.
- quicksort's outer latch decrements j in j's own register: the new j lives
  in a hole of the old j's interval, so no copy surrounds the SUB.
The programs run and are checked for their output first."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"

fn count_down(n: i64, total: i64) i64 {
  if n == 0 {
    return total
  }
  return count_down(n - 1, total + n)
}

fn quicksort(values: []u64) {
  if #len(values) < 2 {
    return
  }
  pivot := values[(#len(values) - 1) / 2]
  i: usize = 0
  j := #len(values) - 1
  for {
    for values[i] < pivot {
      i += 1
    }
    for values[j] > pivot {
      j -= 1
    }
    if i >= j {
      break
    }
    swap := values[i]
    values[i] = values[j]
    values[j] = swap
    i += 1
    j -= 1
  }
  quicksort(values[..j + 1])
  quicksort(values[j + 1..])
}

fn probe(keys: []u64, key: u64) usize {
  at := #cast(usize, (key * 11400714819323198485) >> 54)
  for keys[at] != 0 && keys[at] != key {
    at = (at + 1) & 1023
  }
  return at
}

fn mix(n: u64) u64 {
  state: u64 = 7
  for _ in 0..n {
    state = state * 6364136223846793005 + 1442695040888963407
    state ^= state >> 29
  }
  return state
}

fn main() {
  values: [64]u64
  state: u64 = 3
  for i in 0..64 {
    state = state * 6364136223846793005 + 1
    values[i] = state >> 40
  }
  quicksort(values[..])
  sorted := true
  for i in 1..64 {
    if values[i - 1] > values[i] {
      sorted = false
    }
  }
  keys: [1024]u64
  keys[probe(keys[..], 5)] = 5
  io.println("{} {} {} {}", count_down(10000000, 0), sorted, probe(keys[..], 5) < 1024, mix(1000) != 0)
}
'''
if not shutil.which('objdump'):
    print('SKIP codegen shapes: objdump missing')
    raise SystemExit(0)


def function(listing, name):
    body = re.search(rf'<{name}>:\n(.*?)\n\n', listing, re.S)
    assert body, name
    return [line.split('\t', 1)[-1].strip() for line in body.group(1).splitlines()]


with tempfile.TemporaryDirectory(prefix='dyn-ssa-codegen-shape-') as temporary:
    source = Path(temporary) / 'main.dyn'
    source.write_text(SOURCE)
    program = Path(temporary) / 'program'
    subprocess.run([DYN, 'build', str(source), '--release', '--no-cache', '--quiet', '--output', str(program)],
                   check=True, timeout=120, env={**os.environ, 'DYN_NO_INLINE': '1'})
    result = subprocess.run([str(program)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and result.stdout == '50000005000000 true true true\n', result
    listing = subprocess.run(['objdump', '-d', '--no-show-raw-insn', str(program)], capture_output=True, text=True,
                             check=True).stdout
    count_down = function(listing, 'count_down')
    assert not any('call' in line for line in count_down), count_down
    quicksort = function(listing, 'quicksort')
    assert sum('call' in line and '<quicksort>' in line for line in quicksort) == 1, quicksort
    # Rotated inner loops: their back edges are conditional branches; only
    # the outer `for {}` still jumps back, into the first inner header.
    body = re.search(r'<quicksort>:\n(.*?)\n\n', listing, re.S).group(1).splitlines()
    backward = [l for l in body if re.search(r'\tjmp\s+([0-9a-f]+) <quicksort', l) and
                int(re.search(r'jmp\s+([0-9a-f]+)', l).group(1), 16) < int(l.split(':')[0], 16)]
    assert len(backward) <= 1, backward
    for i, line in enumerate(quicksort):
        if re.match(r'sub\s+\$0x1,', line) and i + 1 < len(quicksort) and quicksort[i + 1].startswith('jmp'):
            register = line.split(',')[-1]
            assert not quicksort[i - 1].endswith(',' + register) or quicksort[i - 1].startswith('add'), quicksort[i - 2:i + 2]
            break
    else:
        raise AssertionError(quicksort)
    probe = function(listing, 'probe')
    for i, line in enumerate(probe):
        if line.startswith('and') and '$0x3ff' in line:
            register = line.split(',')[-1]
            assert probe[i - 1].startswith('add') and probe[i - 1].endswith(register), probe[i - 2:i + 1]
            break
    else:
        raise AssertionError(probe)
    mix = function(listing, 'mix')
    loop = [l for l in mix if l.startswith('imul') or l.startswith('movabs')]
    assert sum(l.startswith('movabs') for l in mix) == 2 and not any(
        mix[i].startswith('movabs') and any(m.startswith('imul') for m in mix[:i]) for i in range(len(mix))), mix
print('PASS tail calls loop, two-address chains share the phi register, wide loop constants stay in registers, quicksort latch has no copies')
