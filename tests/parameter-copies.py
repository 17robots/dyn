#!/usr/bin/env python3
"""Struct and array parameters are copies, whatever the backend does to
avoid copying them: an inlined body may read the caller's local in place, a
callee may keep a stack-passed struct where it arrived or read a by-pointer
one through the pointer, and a caller may pass a local without a snapshot.
Writes to a parameter never reach the caller, and a caller's later writes
never reach a parameter, in debug and release, on x86-64 Linux and, where
an emulator is installed, AArch64 Linux and x86-64 Windows."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import private_display  # hides the desktop display; see tests/private_display.py

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/io"

struct Big { a: i64, b: i64, c: i64, d: i64, e: i64, f: i64, g: i64, h: i64 }

fn sum(v: Big) i64 {
  return v.a + v.b + v.c + v.d + v.e + v.f + v.g + v.h
}

// Writes its own copy; the caller's value must not change.
fn scribble(v: Big) i64 {
  v.a = 1000
  v.h += 7
  return sum(v)
}

// Two parameters given the same local: writing one leaves the other.
fn pair(left: Big, right: Big) i64 {
  left.b = 500
  return left.b + right.b
}

// Recursive, so never inlined: the struct travels through real calls.
fn deep(v: Big, depth: u32) i64 {
  if depth == 0 { return sum(v) }
  return deep(v, depth - 1) + v.a
}

fn deep_scribble(v: Big, depth: u32) i64 {
  v.a += 1
  if depth == 0 { return v.a }
  return deep_scribble(v, depth - 1) + v.a
}

fn grid(cells: [6]i64) i64 {
  total: i64 = 0
  for cell in cells { total += cell }
  return total
}

fn grid_scribble(cells: [6]i64) i64 {
  cells[0] = 100
  return grid(cells)
}

fn main() {
  v := Big{ a: 1, b: 2, c: 3, d: 4, e: 5, f: 6, g: 7, h: 8 }
  first := sum(v)
  changed := scribble(v)
  after := sum(v)
  both := pair(v, v)
  recursive := deep(v, 4)
  recursive_changed := deep_scribble(v, 3)
  cells: [6]i64 = [1, 2, 3, 4, 5, 6]
  grid_total := grid(cells)
  grid_changed := grid_scribble(cells)
  io.println("{} {} {} {} {} {} {} {} {} {}", first, changed, after, both, recursive, recursive_changed,
    v.a, grid_total, grid_changed, cells[0])
}
'''
EXPECTED = '36 1042 36 502 40 14 1 21 120 1\n'
runners = [('x86_64-linux', [])]
if shutil.which('qemu-aarch64'):
    runners.append(('aarch64-linux', ['qemu-aarch64']))
if shutil.which('wine'):
    runners.append(('x86_64-windows', ['wine']))
with tempfile.TemporaryDirectory(prefix='dyn-parameter-copies-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    for target, runner in runners:
        for flags in ([], ['--release']):
            output = project / ('program.exe' if 'windows' in target else 'program')
            subprocess.run([DYN, 'build', str(project), '--target', target, '--quiet', '--no-cache',
                            '--output', str(output), *flags], check=True, timeout=120)
            result = subprocess.run([*runner, str(output)], capture_output=True, text=True, timeout=60,
                                    env=dict(os.environ, WINEDEBUG='-all'))
            assert result.stdout.replace('\r', '') == EXPECTED, (target, flags, result.stdout, result.stderr)
print(f'PASS parameter copies: struct and array parameters stay copies ({", ".join(t for t, _ in runners)}; debug/release)')
