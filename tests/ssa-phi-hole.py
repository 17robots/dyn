#!/usr/bin/env python3
"""A loop total exits from the loop header yet is updated in place: the update
shares the total's register through the hole after it, so no copies remain."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"
use "std/mem"

fn main() {
  arena := mem.arena_create(0)
  xs := mem.push_array(f32, arena, 1000)
  for i in 0..1000 {
    xs[i] = #cast(f32, i) * 0.5
  }
  e: f32 = 0.0
  for r in 0..1000 {
    for i in 0..1000 {
      e += xs[i] * 0.001
    }
  }
  io.println("{}", #cast(i64, e))
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-phi-hole-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE)
    outputs = []
    for name, flags in (('debug', ['--debug']), ('o3', ['--release', '--opt-level', '3'])):
        program = work / name
        subprocess.run([DYN, 'build', str(work), *flags, '--quiet', '--no-cache', '--output', str(program)],
                       check=True, timeout=120)
        outputs.append(subprocess.run([str(program)], capture_output=True, text=True, timeout=60, check=True).stdout)
    assert outputs[0] == outputs[1], outputs
    if os.uname().machine == 'x86_64':
        asm = subprocess.run(['objdump', '-d', '--no-show-raw-insn', str(work / 'o3')],
                             capture_output=True, text=True, check=True).stdout
        main = re.search(r'<main>:\n(.*?)(?=\n\n|\Z)', asm, re.S)[1]
        # The inner loop: from the target of its closing jb back to that jb.
        lines = main.splitlines()
        bodies = []
        for jump in [l for l in lines if re.search(r'\tjb\s', l)]:
            target = re.search(r'jb\s+([0-9a-f]+)', jump)[1]
            starts = [i for i, l in enumerate(lines) if l.strip().startswith(target + ':')]
            if starts and starts[0] < lines.index(jump):
                bodies.append('\n'.join(lines[starts[0]:lines.index(jump) + 1]))
        body = min((b for b in bodies if 'addss' in b), key=len)
        assert 'addss' in body and 'movaps' not in body, body
print('PASS phi hole: loop total updated in place, debug and O3 agree')
