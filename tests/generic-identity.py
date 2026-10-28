#!/usr/bin/env python3
"""Generic symbols distinguish equal diagnostic names from different packages."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-generic-identity-') as directory:
    work = Path(directory)
    for name, size in (('left', 1), ('right', 7)):
        package = work / name
        package.mkdir()
        (package / 'main.dyn').write_text('''use "std/mem" mem
pub struct Event { bytes: [''' + str(size) + ''']u64 }
pub enum Mode { A, B }
pub distinct type Id = u64
type Transform = fn(Event) Event
pub fn exercise() usize {
  arena := mem.arena_create(0)
  defer { mem.arena_release(arena) }
  events := mem.push_array(Event, arena, 2)
  pointers := mem.push_array(*Event, arena, 2)
  arrays := mem.push_array([2]Event, arena, 2)
  slices := mem.push_array([]const Event, arena, 2)
  functions := mem.push_array(Transform, arena, 2)
  modes := mem.push_array(Mode, arena, 2)
  ids := mem.push_array(Id, arena, 2)
  return #sizeof(Event) + #len(events) + #len(pointers) + #len(arrays) + #len(slices) + #len(functions) + #len(modes) + #len(ids)
}
''')
    (work / 'main.dyn').write_text('''use "left"
use "right"
fn main() {
  if left.exercise() != 22 || right.exercise() != 70 { #panic("generic nominal identity") }
}
''')
    for mode in ('--debug', '--release'):
        for cached in (False, True):
            command = [DYN, 'build', str(work), mode, '--quiet', '--output', str(work / 'program')]
            if not cached:
                command += ['--no-cache']
            subprocess.run(command, check=True, timeout=300)
            subprocess.run([str(work / 'program')], check=True, timeout=30)
print('PASS generic identity: structs, enums, distincts, nested pointers/arrays/slices/functions, debug/release/cache')
