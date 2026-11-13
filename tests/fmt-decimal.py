#!/usr/bin/env python3
"""Decimal writers against Python integers, with bounded-buffer failure checks."""
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
rng = random.Random(1967)
unsigned = {0, 1, 2**64 - 1, 2**63, 2**63 - 1}
for exponent in range(20):
    for offset in (-1, 0, 1):
        value = 10**exponent + offset
        if 0 <= value < 2**64:
            unsigned.add(value)
unsigned.update(rng.getrandbits(64) for _ in range(1200))
unsigned = sorted(unsigned)
signed = {-(2**63), 2**63 - 1, -1, 0, 1}
for value in unsigned:
    if value < 2**63:
        signed.update((value, -value))
signed.update(rng.randrange(-(2**63), 2**63) for _ in range(1200))
signed = sorted(signed)

def array(values):
    return ',\n'.join('  ' + ', '.join(map(str, values[i:i+8])) for i in range(0, len(values), 8))

SOURCE = f'''use "std/fmt" fmt
use "std/io" io
use "std/mem" mem
const unsigned: [{len(unsigned)}]u64 = [
{array(unsigned)}
]
const signed_bits: [{len(signed)}]u64 = [
{array([value % 2**64 for value in signed])}
]
fn check_unsigned(value: u64) {{
  full: [20]u8
  reference := fmt.buffer(full[..])
  fmt.write_u64(&reference, value)
  if reference.failed {{ #panic("full unsigned") }}
  io.println("{{}}", fmt.bytes(&reference))
  bounded: [24]u8
  for capacity in 0..22 {{
    for i in 0..#len(bounded) {{ bounded[i] = '!' }}
    state := fmt.buffer(bounded[..capacity])
    enough := capacity >= reference.length
    fmt.write_u64(&state, value)
    if state.failed == enough {{ #panic("unsigned capacity") }}
    if enough {{
      if !mem.equal(fmt.bytes(&state), fmt.bytes(&reference)) {{ #panic("unsigned bytes") }}
    }} else {{
      fmt.write_u64(&state, 0)
      if state.length != 0 || bounded[0] != '!' || !state.failed {{ #panic("unsigned rollback/sticky") }}
    }}
    if bounded[capacity] != '!' {{ #panic("unsigned overwrite") }}
  }}
}}
fn check_signed(bits: u64) {{
  value := #bitcast(i64, bits)
  full: [20]u8
  reference := fmt.buffer(full[..])
  fmt.write_i64(&reference, value)
  if reference.failed {{ #panic("full signed") }}
  io.println("{{}}", fmt.bytes(&reference))
  bounded: [24]u8
  for capacity in 0..22 {{
    for i in 0..#len(bounded) {{ bounded[i] = '!' }}
    state := fmt.buffer(bounded[..capacity])
    enough := capacity >= reference.length
    fmt.write_i64(&state, value)
    if state.failed == enough {{ #panic("signed capacity") }}
    if enough {{
      if !mem.equal(fmt.bytes(&state), fmt.bytes(&reference)) {{ #panic("signed bytes") }}
    }} else {{
      fmt.write_i64(&state, 0)
      if state.length != 0 || bounded[0] != '!' || !state.failed {{ #panic("signed rollback/sticky") }}
    }}
    if bounded[capacity] != '!' {{ #panic("signed overwrite") }}
  }}
}}
fn main() {{
  for value in unsigned {{ check_unsigned(value) }}
  for bits in signed_bits {{ check_signed(bits) }}
  storage: [32]u8
  state := fmt.buffer(storage[..])
  fmt.write(&state, "id=")
  fmt.write_i64(&state, -42)
  if state.failed || !mem.equal(fmt.bytes(&state), "id=-42") {{ #panic("append prefix") }}
  fmt.clear(&state)
  fmt.write_u64_width(&state, 42, 5, '0')
  if state.failed || !mem.equal(fmt.bytes(&state), "00042") {{ #panic("padding") }}
  fmt.clear(&state)
  fmt.print(&state, "{{}}-{{}} {{{{ok}}}}", 7, "x")
  if state.failed || !mem.equal(fmt.bytes(&state), "7-x {{ok}}") {{ #panic("print") }}
  small: [4]u8
  tight := fmt.buffer(small[..])
  fmt.print(&tight, "ab{{}}", 123)
  if !tight.failed || tight.length != 0 {{ #panic("print rollback") }}
}}
'''
expected = list(map(str, unsigned + signed))
with tempfile.TemporaryDirectory(prefix='dyn-fmt-decimal-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    for release in (False, True):
        output = project / 'program'
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output)] + (['--release'] if release else []), check=True, timeout=120)
        actual = subprocess.run([str(output)], check=True, capture_output=True, text=True, timeout=30).stdout.splitlines()
        assert actual == expected, next(((i, a, e) for i, (a, e) in enumerate(zip(actual, expected)) if a != e), (len(actual), len(expected)))
print(f'PASS decimal formatting: {len(unsigned)} unsigned and {len(signed)} signed Python-oracle values, capacities 0..21, rollback/sticky and append/padding (debug/release)')
