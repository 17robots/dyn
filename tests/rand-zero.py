#!/usr/bin/env python3
"""Bounded std/rand zero-state and seeded-sequence regression (debug/release)."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
ENV = {**os.environ, 'DYN_SDK': str(ROOT)}
MODULUS = 2147483647
REJECTION_SEED = (-pow(48271, -1, MODULUS)) % MODULUS


def reference(seed):
    """Park-Miller sequence, calculated with Python's unbounded integers."""
    value = seed % MODULUS or 1
    while True:
        value = value * 48271 % MODULUS
        yield value


def array(values):
    return ','.join(map(str, values))


source = ['''use "std/rand" rand
fn main() {
  zero: rand.State
  explicit := rand.seeded(0)
  default_seed := rand.seeded(1)
  previous: u64 = 0
  for i in 0..128 {
    value := rand.next_u64(&zero)
    if value == 0 || value == previous { #panic("zero sequence must change") }
    if value != rand.next_u64(&explicit) || value != rand.next_u64(&default_seed) { #panic("default sequence equivalence") }
    previous = value
  }
''']
# Include normalization boundaries and a seed whose first draw is rejected by
# below(3), so the rejection loop is exercised as well as zero initialization.
for index, seed in enumerate((0, 1, 42, 123456789, MODULUS - 1,
                              MODULUS, MODULUS + 1, 18446744073709551615)):
    oracle = reference(seed)
    golden = [next(oracle) for _ in range(64)]
    source.append(f'''
  state_{index} := rand.seeded({seed})
  golden_{index}: [64]u64 = [{array(golden)}]
  for expected in golden_{index} {{
    if rand.next_u64(&state_{index}) != expected {{ #panic("seed golden") }}
  }}
''')
assert next(reference(REJECTION_SEED)) == MODULUS - 1
for index, seed in enumerate((0, REJECTION_SEED)):
    oracle = reference(seed)
    golden = []
    while len(golden) < 128:
        value = next(oracle) - 1
        if value < (MODULUS - 1) - (MODULUS - 1) % 3:
            golden.append(value % 3)
    declaration = 'bounded_0: rand.State' if seed == 0 else f'bounded_{index} := rand.seeded({seed})'
    source.append(f'''
  {declaration}
  below_golden_{index}: [128]u64 = [{array(golden)}]
  for expected in below_golden_{index} {{
    value := rand.below(&bounded_{index}, 3)
    if value >= 3 || value != expected {{ #panic("below range/oracle") }}
  }}
''')
fill_oracle = reference(0)
fill_golden = [next(fill_oracle) % 256 for _ in range(97)]
next_after_fill = next(fill_oracle)
source.append(f'''
  fill_state: rand.State
  output: [97]u8
  expected_bytes: [97]u8 = [{array(fill_golden)}]
  rand.fill(&fill_state, output[..0])
  rand.fill(&fill_state, output[..31])
  rand.fill(&fill_state, output[31..])
  for i in 0..97 {{
    if output[i] != expected_bytes[i] {{ #panic("fill oracle") }}
  }}
  if rand.next_u64(&fill_state) != {next_after_fill} {{ #panic("fill consumption") }}
}}
''')
with tempfile.TemporaryDirectory(prefix='dyn-rand-zero-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text('\n'.join(source))
    for mode in ('debug', 'release'):
        output = work / mode
        subprocess.run([DYN, 'build', str(work), '--' + mode, '--quiet',
                        '--no-cache', '--output', str(output)],
                       env=ENV, check=True, timeout=120)
        subprocess.run([str(output)], env=ENV, check=True, timeout=10)
        print('PASS rand zero/default, below, fill, seeded Python oracles ' + mode,
              flush=True)
