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
  arena := mem.arena_alloc(0)
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

# One spelling per generic: `$T: type` is an error when an argument's type
# already carries T, and inferred generics name instances as function values.
REDUNDANT = '''fn first(T: type, items: []T) T {
  return items[0]
}

fn sizes(T: type, count: usize) usize {
  return count * #sizeof(T)
}

fn main() {
  values: [2]u8 = [1, 2]
  _ = first(u8, values[..])
  _ = sizes(u32, 2)
}
'''
INSTANCE = '''fn mix(seed: u64, key: $K) u64 {
  return seed + #cast(u64, key)
}

fn main() {
  hash := #instance(mix, u32)
  if hash(1, 2) != 3 {
    #panic("instance value")
  }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-generic-spelling-') as directory:
    work = Path(directory) / 'redundant'
    work.mkdir()
    (work / 'main.dyn').write_text(REDUNDANT)
    result = subprocess.run([DYN, 'check', str(work)], capture_output=True, text=True, timeout=60)
    errors = [line for line in result.stderr.splitlines() if ': error:' in line]
    assert result.returncode != 0 and len(errors) == 1, result.stderr
    assert ':1:10: error: T is in the type of `items`, so it is inferred' in errors[0], result.stderr
    work = Path(directory) / 'instance'
    work.mkdir()
    (work / 'main.dyn').write_text(INSTANCE)
    result = subprocess.run([DYN, 'run', str(work), '--quiet'], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
print('PASS generic errors: conflicts name the binding argument; std instance failures land on the program call; one generic spelling; inferred instance values')

# A bad generic signature is reported once and does not stop later functions
# from being declared, so their bodies raise no false errors.
CASCADE = '''fn make(items: []$T, state: *T) i32 {
  return 0
}

fn other() i32 {
  return 1
}

fn main() {
  _ = other()
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-generic-cascade-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(CASCADE)
    result = subprocess.run([DYN, 'check', str(work)], capture_output=True, text=True, timeout=60)
    errors = [line for line in result.stderr.splitlines() if ': error:' in line]
    assert result.returncode != 0 and len(errors) == 1, result.stderr
    assert 'in every parameter that supplies it' in errors[0], result.stderr
print('PASS generic signature errors do not cascade')
