#!/usr/bin/env python3
"""Locals over 256 bytes are zeroed by a loop of 16-byte stores up to 4 KiB
(rep stosb only past that): every size class, its 16-byte and smaller tails,
is all zero each time it is declared again, in debug and release and on
x86-64 Windows under Wine when it is installed."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SIZES = (257, 280, 296, 303, 320, 1000, 4095, 4096, 4097, 9000)
structs = ''.join(f'struct S{size} {{ bytes: [{size}]u8 }}\n' for size in SIZES)
checks = ''.join(f'''  for round in 0..3 {{
    value{size}: S{size}
    for b in value{size}.bytes {{
      if b != 0 {{ bad += 1 }}
    }}
    for i in 0..{size} {{
      value{size}.bytes[i] = #cast(u8, (i + round) % 255 + 1)
    }}
    total += value{size}.bytes[{size} - 1]
  }}
''' for size in SIZES)
SOURCE = f'''use "std/io"

{structs}
fn main() {{
  bad: usize = 0
  total: usize = 0
{checks}  io.println("{{}} {{}}", bad, total)
}}
'''
with tempfile.TemporaryDirectory(prefix='dyn-zero-locals-') as temporary:
    project = Path(temporary) / 'zero'
    project.mkdir()
    (project / 'main.dyn').write_text(SOURCE)
    outputs = set()
    targets = [None] + (['x86_64-windows'] if shutil.which('wine') else [])
    for target in targets:
        for mode in ('--debug', '--release'):
            output = Path(temporary) / ('program' + ('.exe' if target else ''))
            subprocess.run([DYN, 'build', str(project), mode, '--quiet', '--no-cache', '--output', str(output),
                            *(['--target', target] if target else [])], check=True, timeout=180)
            run = subprocess.run((['wine'] if target else []) + [str(output)], capture_output=True, text=True,
                                 timeout=120, env=dict(os.environ, WINEDEBUG='-all'))
            assert run.returncode == 0, run
            outputs.add(run.stdout.strip())
    assert len(outputs) == 1 and next(iter(outputs)).startswith('0 '), outputs
print(f'PASS zeroed locals: {len(SIZES)} sizes from 257 bytes to 9000, loop and rep stosb paths ({len(targets) * 2} builds)')
