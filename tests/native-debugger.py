#!/usr/bin/env python3
"""Native debug executables carry DWARF lines, frames, parameters, scoped typed locals
and payload enums."""
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = os.environ.get('DYN', str(ROOT / 'build/dyn'))
if not sys.platform.startswith('linux') or platform.machine() != 'x86_64' or not shutil.which('gdb'):
    print('SKIP native debugger contracts: requires x86_64 Linux and gdb')
    sys.exit(0)

SOURCE = '''struct Point {
  x: i64,
  y: i64,
}
enum Color { Red, Green }
enum Shape { Circle: f64, Square: i64, Empty }
fn scoped(a: i64, s: Shape) i64 {
  total := a
  if a > 0 {
    x := a * 2
    total += x
  } else {
    x := a * 3
    total += x
  }
  _ = s
  return total
}
fn add(a: i64, b: i64) i64 {
  c := a + b
  p := Point{x: a, y: b}
  col := Color.Green
  name := "hey"
  values: [3]u8 = [1, 2, 3]
  _ = p
  _ = col
  _ = name
  _ = values
  return c
}
fn main() {
  x := add(2, 3)
  if x != 5 || scoped(5, Shape.Square(4)) != 15 { #panic("bad") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-native-debugger-') as directory:
    root = Path(directory)
    (root / 'app').mkdir()
    (root / 'app/main.dyn').write_text(SOURCE)
    program = root / 'program'
    built = subprocess.run([DYN, 'build', str(root / 'app'), '--backend', 'native', '--quiet',
                            '--no-cache', '--output', str(program)],
                           capture_output=True, text=True, timeout=120)
    if built.returncode == 2 and '--backend native requires' in built.stderr:
        print('SKIP native debugger contracts: compiler built without the native backend')
        sys.exit(0)
    assert built.returncode == 0, built.stderr
    session = subprocess.run(['gdb', '-batch', '-nx', '-ex', 'set debuginfod enabled off',
                              '-ex', 'break main.dyn:29', '-ex', 'run',
                              '-ex', 'info locals', '-ex', 'print p.y',
                              '-ex', 'print *name.data@name.len', '-ex', 'print values',
                              '-ex', 'ptype p', '-ex', 'backtrace',
                              '-ex', 'break main.dyn:11', '-ex', 'continue', '-ex', 'info locals',
                              '-ex', 'print s.payload.Square', '-ex', 'print s.tag', str(program)],
                             capture_output=True, text=True, timeout=60)
    printers = subprocess.run(['gdb', '-batch', '-nx', '-ex', 'set debuginfod enabled off',
                               '-ex', 'source ' + str(ROOT / 'tools/debugger/dyn_gdb.py'),
                               '-ex', 'break main.dyn:29', '-ex', 'run',
                               '-ex', 'print name', '-ex', 'print values', str(program)],
                              capture_output=True, text=True, timeout=60)
    assert '$1 = "hey"' in printers.stdout, (printers.stdout, printers.stderr)
    output = session.stdout
    for expected in ('add (a=2, b=3) at', 'main.dyn:29', 'c = 5', 'p = {x = 2, y = 3}',
                     'col = Green', '$1 = 3', '$2 = "hey"', '$3 = "\\001\\002\\003"',
                     'struct Point {', 'in main () at',
                     'scoped (a=5, s=...) at', 'x = 10\ntotal = 5', '$4 = 4', '$5 = Square'):
        assert expected in output, (expected, output, session.stderr)
print('PASS native debugger: lines, frames, parameters, scoped locals, structs, enums, payloads, strings and arrays')
