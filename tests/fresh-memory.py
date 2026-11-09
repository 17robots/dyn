#!/usr/bin/env python3
"""Loads from one arena allocation survive stores into another, as with LLVM's
noalias results; memory reached another way, such as an arena's backing
buffer, still may overlap."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"
use "std/mem"

fn through_backing(backing: []u64, view: []u64) u64 {
  first := view[0]
  backing[0] = first + 5
  return view[0]
}

// Pushes from an arena built on another's buffer lie inside that buffer.
fn overlap(storage: []u8, view: []u64) u64 {
  before := view[0]
  for i in 0..#len(storage) {
    storage[i] = 0
  }
  return before * 100 + view[0]
}

fn main() {
  arena := mem.arena_create(0)
  ps := mem.push_array(f32, arena, 64)
  vs := mem.push_array(f32, arena, 64)
  for i in 0..64 {
    vs[i] = #cast(f32, i)
  }
  e: f32 = 0.0
  for r in 0..1000 {
    for i in 0..64 {
      ps[i] = ps[i] + vs[i] * 0.5
      e += ps[i] * vs[i]
    }
  }
  storage := mem.push_array(u8, arena, 4096)
  inner := mem.arena_from_buffer(storage)
  view := mem.push_array(u64, inner, 4)
  view[0] = 7
  storage[0] = 1
  io.println("{} {} {}", #cast(i64, e), through_backing(view, view), overlap(storage, view))
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-fresh-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE)
    outputs = []
    for name, flags in (('debug', ['--debug']), ('o3', ['--release', '--opt-level', '3'])):
        program = work / name
        result = subprocess.run([DYN, 'build', str(work), *flags, '--quiet', '--no-cache', '--opt-remarks',
                                 '--output', str(program)], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        if name == 'o3':
            assert re.search(r'main: \d+ repeated loads reused', result.stderr), result.stderr
        outputs.append(subprocess.run([str(program)], capture_output=True, text=True, timeout=60, check=True).stdout)
    assert outputs[0] == outputs[1] and outputs[0].split()[1:] == ['12', '1200'], outputs
print('PASS fresh memory: loads kept across stores into other allocations, aliasing views reread')
