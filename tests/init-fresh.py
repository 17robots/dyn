#!/usr/bin/env python3
"""#init(p) makes *p a fresh value, zero then field defaults, for every type,
over dirty memory, in debug and release and on the tree code generator."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"
use "std/mem"

enum Color { Red, Green, Blue }
enum Shape { Dot, Circle(f64) }
struct Settings { size: i32 = 7, name: []const u8 = "x", flags: u64 }

fn dirty<T>(arena: *mem.Arena) *T {
  value := mem.push<T>(arena)
  bytes := #slice(#cast(*u8, value), #sizeof(T))
  for i in 0..bytes.len { bytes[i] = 0xab }
  return value
}

fn main() {
  arena := mem.arena_alloc(0)
  defer mem.arena_release(arena)
  s := dirty<Settings>(arena)
  #init(s)
  n := dirty<u64>(arena)
  #init(n)
  a := dirty<[5]u16>(arena)
  #init(a)
  t := dirty<[]const u8>(arena)
  #init(t)
  c := dirty<Color>(arena)
  #init(c)
  p := dirty<Shape>(arena)
  #init(p)
  f := dirty<f64>(arena)
  #init(f)
  pushed := mem.push<Settings>(arena)
  io.println("{} {} {} {} {} {} {} {} {}", s.size, s.name, s.flags, n.*, a.*[4], t.*.len, c.* == Color.Red, f.*, pushed.size)
  case p.* {
    Shape.Dot => { io.println("dot") }
    _ => { io.println("not dot") }
  }
}
'''
EXPECTED = '7 x 0 0 0 0 true 0 7\ndot\n'
with tempfile.TemporaryDirectory(prefix='dyn-init-fresh-') as temporary:
    project = Path(temporary) / 'project'
    project.mkdir()
    (project / 'main.dyn').write_text(SOURCE)
    for name, flags, env in (('debug', ['--debug'], {}), ('release', ['--release'], {}),
                             ('tree', ['--release'], {'DYN_NO_SSA': '1'})):
        program = Path(temporary) / name
        subprocess.run([DYN, 'build', str(project), *flags, '--quiet', '--no-cache', '--output', str(program)],
                       check=True, timeout=180, env={**os.environ, **env})
        output = subprocess.run([str(program)], capture_output=True, text=True, check=True, timeout=30).stdout
        assert output == EXPECTED, (name, output)
print('PASS #init: zero then defaults for structs, numbers, arrays, slices, enums (debug, release, tree)')
