#!/usr/bin/env python3
"""Delimited casts preserve conversion behavior and reject the removed prefix form."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''calls: i32
fn next() i32 { calls += 1
return 7 }
fn identity(value: i32) i32 { return value }
fn generic(value: $T) i64 { return #cast(i64, value) }
struct Item { value: i32 }
enum(u8) Op { None = 0, Read = 1, Write = 2 }
fn main() {
  if #cast(i64, next() + 2) * 3 != 27 || calls != 1 { #panic("evaluation") }
  if #cast(u8, 257) != 1 || generic(#cast(i16, -7)) != -7 { #panic("numeric") }
  bits := #bitcast(u32, #cast(f32, 1))
  if bits != 1065353216 || #bitcast(f32, bits) != 1.0 { #panic("bits") }
  if #cast(Op, #cast(u8, 2)) != Op.Write { #panic("enum") }
  storage: [2]i32 = [4, 5]
  memory: rawptr = &storage[0]
  if #cast(*i32, memory)[..2][1] != 5 { #panic("postfix slice") }
  item := Item{value: 9}
  erased: rawptr = &item
  if #cast(*Item, erased).value != 9 { #panic("postfix field") }
  if #cast(fn(i32) i32, identity)(11) != 11 { #panic("postfix call") }
  if #cast(i32 /* target */, /* value */ 3 + 4) != 7 { #panic("comments") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-cast-syntax-') as temporary:
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
    subprocess.run([DYN, 'check', str(project), '--no-cache', '--quiet'], check=True, timeout=30)
    for expression in ('#cast(i32) 1', '#bitcast(u32) 1.0'):
        source.write_text(f'fn main() {{ _ = {expression} }}')
        result = subprocess.run([DYN, 'check', str(project), '--no-cache'], capture_output=True, text=True, timeout=30)
        assert result.returncode == 1 and 'prefix cast syntax is no longer supported' in result.stderr, result.stderr
    for expression in ('#cast(i32)', '#cast(i32,)', '#cast(i32, 1, 2)', '#cast(i32, 1', '#bitcast(u64, 1.0, 2)'):
        source.write_text(f'fn main() {{ _ = {expression} }}')
        result = subprocess.run([DYN, 'check', str(project), '--no-cache'], capture_output=True, text=True, timeout=30)
        assert result.returncode == 1, (expression, result.stderr)
print('PASS delimited casts, single evaluation, nesting, postfixes, formatting and removed syntax')
