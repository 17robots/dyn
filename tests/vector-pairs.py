#!/usr/bin/env python3
"""Two-lane f32 pairs: release results match debug bit for bit, including
subtraction, swapped lanes, a store between the loads, overlapping arrays and
stored values that earlier blocks also read, and the pair code appears where
it should."""
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"
use "std/mem"

struct V { x: f32, y: f32 }

fn mix(ps: []V, vs: []V, k: f32) f32 {
  e: f32 = 0.0
  for i in 0..ps.len {
    ps[i] = V{ x: ps[i].x - vs[i].x * k, y: ps[i].y - vs[i].y * k }
    e += ps[i].x * vs[i].x + ps[i].y * vs[i].y
  }
  return e
}

fn swapped(ps: []V, vs: []V) {
  for i in 0..ps.len {
    ps[i] = V{ x: vs[i].y + ps[i].x, y: vs[i].x + ps[i].y }
  }
}

fn between(ps: []V, vs: []V) {
  for i in 0..ps.len {
    a := vs[i].x
    vs[i].y = a * 0.5
    ps[i] = V{ x: a + ps[i].x, y: vs[i].y + ps[i].y }
  }
}

fn shifted(ps: []V) {
  for i in 1..ps.len {
    ps[i] = V{ x: ps[i - 1].x * 0.25 + ps[i].x * 0.5, y: ps[i - 1].y * 0.25 + ps[i].y * 0.5 }
  }
}

struct Box { x: f32, y: f32, width: f32, height: f32 }
struct Last { origin_x: i32, origin_y: i32, box: Box, valid: bool }

// x and y are read by a short-circuit chain, in blocks before the paired
// store of the same values: those reads must keep the scalar values.
fn framed(last: *Last, box: *const Box) bool {
  x := box.x + #cast(f32, last.origin_x)
  y := box.y + #cast(f32, last.origin_y)
  previous := last.box
  inside := last.valid && x > previous.x && y > previous.y && x - previous.x <= 2.5 && y - previous.y <= 2.5
  last.box = Box{ x: x, y: y, width: box.width, height: box.height }
  last.valid = true
  return inside
}

fn bits(ps: []V) u64 {
  h: u64 = 1469598103934665603
  for p in ps {
    h = (h ^ #cast(u64, #bitcast(u32, p.x))) * 1099511628211
    h = (h ^ #cast(u64, #bitcast(u32, p.y))) * 1099511628211
  }
  return h
}

fn main() {
  arena := mem.arena_alloc(0)
  ps := mem.push_array<V>(arena, 257)
  vs := mem.push_array<V>(arena, 257)
  for i in 0..257 {
    f := #cast(f32, i)
    ps[i] = V{ x: f * 0.37 - 41.0, y: 1.0 / (f + 0.5) }
    vs[i] = V{ x: 0.001 * f, y: -f * 1.0e-3 }
  }
  e: f32 = 0.0
  for r in 0..50 {
    e += mix(ps, vs, 0.013)
    swapped(ps, vs)
    between(ps, vs)
    shifted(ps)
  }
  last := Last{}
  frames: u32 = 0
  for i in 0..257 {
    f := #cast(f32, i % 7)
    box := Box{ x: f, y: f + 1.0, width: 30.0 - f, height: 40.0 - f }
    if framed(&last, &box) {
      frames += 1
    }
  }
  io.println("{} {} {} {}", #bitcast(u32, e), bits(ps), bits(vs), frames)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-pairs-') as directory:
    work = Path(directory)
    (work / 'main.dyn').write_text(SOURCE)
    outputs = []
    remarks = ''
    for name, flags in (('debug', ['--debug', '--no-check-overflow']), ('o2', ['--release', '--opt-level', '2']),
                        ('o3', ['--release', '--opt-level', '3'])):
        program = work / name
        result = subprocess.run([DYN, 'build', str(work), *flags, '--quiet', '--no-cache', '--opt-remarks',
                                 '--output', str(program)], capture_output=True, text=True, timeout=120)
        assert result.returncode == 0, result.stderr
        if name == 'o3':
            remarks = result.stderr
        outputs.append(subprocess.run([str(program)], capture_output=True, text=True, timeout=60, check=True).stdout)
    assert outputs[0] == outputs[1] == outputs[2], outputs
    # A finite total, so the comparison is of real values, not NaN.
    assert (int(outputs[0].split()[0]) >> 23) & 0xff != 0xff, outputs
    if os.uname().machine == 'x86_64':
        assert re.search(r'paired [1-9]\d* f32 stores and [1-9]\d* dot products', remarks), remarks
print('PASS vector pairs: lanes match debug bit for bit, dot products paired')
