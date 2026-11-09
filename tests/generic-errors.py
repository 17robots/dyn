#!/usr/bin/env python3
"""Generic call errors point at the program: a type conflict names the
argument that fixed the type, and a failure inside a std instance is
reported at the program's call with the library line as a note."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())
SOURCE = '''use "std/container/array"
use "std/container/map"
use "std/mem"

struct Point {
  x: i32,
  y: i32
}

fn main() {
  arena := mem.arena_create(0)
  points: map.Map(Point, u32)
  map.init(&points, arena)
  names: array.Array(u32)
  array.init(&names, arena)
  array.push(&names, "hello")
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-generic-errors-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE)
    result = subprocess.run([DYN, 'check', str(work)], capture_output=True, text=True, timeout=60)
    assert result.returncode != 0, result
    lines = result.stderr.splitlines()
    main = str(work / 'main.dyn')
    assert any(line.startswith(main + ':16:22: error: T is u32 from `&names`, but this argument makes it []const u8')
               for line in lines), result.stderr
    assert any(line.startswith(main + ':13:3: error: #assert failed: map.init: keys must be') for line in lines), result.stderr
    assert any('map.dyn' in line and 'note: reported inside the library here' in line for line in lines), result.stderr
    assert not any('map.dyn' in line and ': error:' in line for line in lines), result.stderr
print('PASS generic errors: conflicts name the binding argument; std instance failures land on the program call')
