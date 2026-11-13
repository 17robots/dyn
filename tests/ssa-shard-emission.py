#!/usr/bin/env python3
"""Workers that emit into shards produce the object serial emission does.

Release builds let each SSA worker emit its functions into a private
context (ssa_shard_new); the driver then places them in order, interning
read-only data, numbering runtime symbols and RISC-V anchors, and rebasing
unwind and landing records (ssa_shard_merge). The program has many
functions with string literals shared between them, index-check messages,
dense `case` jump tables, loops (16-byte entries on x86-64), fmod calls,
frames over a page (__chkstk on Windows) and defers around calls (landing
records). Each target's object must match DYN_SERIAL_EMISSION=1 byte for
byte, and the x86-64 program prints what the serial one prints."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
FUNCTIONS = 48


def function(i):
    return f'''
fn work{i}(values: []u64, n: u64) u64 {{
  total: u64 = {i}
  for k in 0..n {{
    total += values[k % #len(values)] * {i + 1}
  }}
  case total % 6 {{
    0 => {{ total += 11 }}
    1 => {{ total ^= 7 }}
    2 => {{ total *= 3 }}
    3 => {{ total -= 1 }}
    4 => {{ total += {i} }}
    _ => {{ total >>= 1 }}
  }}
  label := "shared label"
  own := "label {i}"
  return total + #len(label) + #len(own)
}}

fn scaled{i}(x: f64) f64 {{
  return (x * {i + 2}.5) % 7.25
}}

fn framed{i}(seed: u64) u64 {{
  buffer: [600]u64
  for k in 0..600 {{
    buffer[k] = seed + k * {i + 3}
  }}
  defer sink += 1
  note(buffer[seed % 600])
  return buffer[(seed * 7) % 600]
}}
'''


SOURCE = 'use "std/io"\n\nsink: u64 = 0\n\nfn note(x: u64) {\n  sink += x\n}\n' + \
    ''.join(function(i) for i in range(FUNCTIONS)) + '''
fn main() {
  values: [5]u64
  for i in 0..5 {
    values[i] = #cast(u64, i) * 13 + 1
  }
  total: u64 = 0
  scaled: f64 = 0.0
''' + ''.join(f'  total += work{i}(values[..], {i + 3})\n  scaled += scaled{i}({i}.75)\n  total += framed{i}({i * 17})\n'
              for i in range(FUNCTIONS)) + '''  io.println("{} {} {}", total, #cast(i64, scaled * 1000.0), sink)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-ssa-shard-emission-') as temporary:
    source = Path(temporary) / 'main.dyn'
    source.write_text(SOURCE)
    for target in ('x86_64-linux', 'aarch64-linux', 'riscv64-linux', 'x86_64-windows', 'aarch64-macos', 'x86_64-macos'):
        objects = {}
        for name, env in (('serial', {'DYN_SERIAL_EMISSION': '1', 'DYN_BACKEND_JOBS': '4'}),
                          ('shards', {'DYN_BACKEND_JOBS': '4'}), ('many', {'DYN_BACKEND_JOBS': '12'})):
            output = Path(temporary) / f'{target}-{name}'
            subprocess.run([DYN, 'build', str(source), '--release', '--target', target, '--no-cache', '--quiet',
                            '--emit-object', '--no-link', '--output', str(output)], check=True, timeout=120,
                           env={**os.environ, **env})
            objects[name] = Path(str(output) + '.o').read_bytes()
        assert objects['shards'] == objects['serial'], (target, 'shard emission changed the object')
        assert objects['many'] == objects['serial'], (target, '12 workers changed the object')
    outputs = []
    for name, env in (('serial', {'DYN_SERIAL_EMISSION': '1'}), ('shards', {})):
        program = Path(temporary) / f'run-{name}'
        subprocess.run([DYN, 'build', str(source), '--release', '--no-cache', '--quiet', '--output', str(program)],
                       check=True, timeout=120, env={**os.environ, **env})
        outputs.append(subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=60).stdout)
    assert outputs[0] == outputs[1] and outputs[0].strip(), outputs
print('PASS shard emission: objects match serial emission on every target')
