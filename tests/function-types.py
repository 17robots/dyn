#!/usr/bin/env python3
"""fn(...) R function types, documentary parameter names, and read-only constant addresses."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''struct Entity { hp: i32, next: *Entity }
struct Hooks { on_hit: fn(target: *Entity, damage: i32) bool, slot: *fn() }
const nil_entity: Entity = Entity{hp: 3}
const limit: i32 = 7
calls: i32
fn hit(target: *Entity, damage: i32) bool {
  target.hp -= damage
  return target.hp <= 0
}
fn count() {
  calls += 1
}
fn pick() fn(i32) i32 {
  return &double
}
fn double(value: i32) i32 {
  return value * 2
}
fn load(slot: *fn(i32) i32, argument: i32) i32 {
  selected := slot.*
  return selected(argument)
}
fn read(e: *const Entity) i32 {
  return e.hp
}
fn main() {
  e := Entity{hp: 5}
  hooks := Hooks{on_hit: &hit}
  if hooks.on_hit(&e, 2) || e.hp != 3 {
    #panic("named parameters")
  }
  run: fn() = &count
  hooks.slot = &run
  hooks.slot.*()
  if calls != 1 || pick()(4) != 8 {
    #panic("function values")
  }
  table: [2]fn(i32) i32 = [&double, &double]
  if table[1](3) != 6 || load(&table[1], 5) != 10 {
    #panic("arrays of functions")
  }
  stub := &nil_entity
  if stub != &nil_entity || read(stub) != 3 || stub.next != nil {
    #panic("constant address")
  }
  if (&limit).* != 7 {
    #panic("scalar constant address")
  }
}
'''
FAILURES = {
    'assignment through *const pointer':
        'struct E { hp: i32 }\nconst n: E = E{}\nfn main() {\n  p := &n\n  p.hp = 1\n}\n',
    'expected *E, found *const E':
        'struct E { hp: i32 }\nconst n: E = E{}\nfn w(p: *E) {\n  p.hp = 1\n}\nfn main() {\n  w(&n)\n}\n',
    'expected *fn(i32) i32, found fn(i32) i32':
        'fn add(a: i32) i32 {\n  return a\n}\nfn main() {\n  f: *fn(i32) i32 = &add\n  _ = f\n}\n',
}
with tempfile.TemporaryDirectory(prefix='dyn-function-types-') as temporary:
    project = Path(temporary)
    source = project / 'main.dyn'
    source.write_text(SOURCE)
    for release in (False, True):
        output = project / ('program.exe' if os.name == 'nt' else 'program')
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet',
                        '--output', str(output), *(['--release'] if release else [])],
                       check=True, timeout=90)
        subprocess.run([str(output)], check=True, timeout=10)
    subprocess.run([DYN, 'fmt', str(project)], check=True, timeout=30)
    subprocess.run([DYN, 'fmt', '--check', str(project)], check=True, timeout=30)
    assert 'fn(target: *Entity, damage: i32) bool' in source.read_text(), source.read_text()
    # A return-less extern followed by a declaration is not a function return type.
    source.write_text('extern fn ping "dyn_ping"()\nfn main() {\n}\n')
    subprocess.run([DYN, 'check', str(project), '--no-cache', '--quiet'], check=True, timeout=30)
    for message, text in FAILURES.items():
        source.write_text(text)
        result = subprocess.run([DYN, 'check', str(project), '--no-cache'], capture_output=True, text=True, timeout=30)
        assert result.returncode == 1 and message in result.stderr, (message, result.stderr)
print('PASS function types: fn(...) R, parameter names, pointers to functions, constant addresses are *const')
