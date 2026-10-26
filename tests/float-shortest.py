#!/usr/bin/env python3
"""fmt.write_f64_shortest: round trip and shortest digits against Python repr."""
from decimal import Decimal
import os
from pathlib import Path
import random
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
rng = random.Random(5)
values = [0.0, -0.0, 1.0, 0.1, 0.3, 1 / 3, 1e-6, 1e-7, 1e20, 1e21, 123.25, 1500.0, 5e-324,
          2.2250738585072014e-308, 1.7976931348623157e308, 0.30000000000000004, -1.5e300, 1e23, 8.41e21]
while len(values) < 6000:
    value = struct.unpack('<d', rng.getrandbits(64).to_bytes(8, 'little'))[0]
    if value == value and abs(value) != float('inf'):
        values.append(value)
values += [rng.uniform(-1e6, 1e6) for _ in range(1000)] + [float(rng.randint(-10**17, 10**17)) for _ in range(500)]
bits = [int.from_bytes(struct.pack('<d', value), 'little') for value in values]
rows = ',\n'.join('  ' + ', '.join(str(b) for b in bits[i:i + 6]) for i in range(0, len(bits), 6))
SOURCE = f'''use "std/fmt" fmt
use "std/io" io
use "std/mem" mem

const values: [{len(bits)}]u64 = [
{rows}
]

fn main() {{
  storage: [64]u8 = []
  for bits in values {{
    state := fmt.buffer(storage[..])
    if !fmt.write_f64_shortest(&state, #bitcast(f64, bits)) {{
      #panic("shortest")
    }}
    _ = io.println(io.stdout(), "{{}}", fmt.bytes(&state))
  }}
  tiny: [3]u8 = []
  small := fmt.buffer(tiny[..])
  if fmt.write_f64_shortest(&small, 0.125) || small.length != 0 || !small.failed {{
    #panic("rollback")
  }}
  backing: [64]u8 = []
  arena := mem.arena_from_buffer(backing[..])
  if !mem.equal(fmt.f64_shortest(&arena, -2.5e-9), "-2.5e-9") {{
    #panic("arena")
  }}
}}
'''


def digits(text):
    sign, shown, exponent = Decimal(text).normalize().as_tuple()
    return shown, exponent + len(shown)


with tempfile.TemporaryDirectory(prefix='dyn-float-shortest-') as directory:
    project = Path(directory)
    (project / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        output = project / 'program'
        subprocess.run([DYN, 'build', str(project), mode, '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=300)
        lines = subprocess.run([str(output)], check=True, capture_output=True, text=True, timeout=60).stdout.split('\n')
        for value, text in zip(values, lines):
            assert struct.pack('<d', float(text)) == struct.pack('<d', value), (value, text)
            if value != 0:
                assert digits(text) == digits(repr(value)), (value, text)
        assert lines[0] == '0' and lines[1] == '-0' and lines[7] == '1e-7' and lines[9] == '1e+21', lines[:10]
print(f'PASS float shortest: {len(values)} binary64 values round trip with Python repr digits, rollback, arena (debug/release)')
