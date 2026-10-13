#!/usr/bin/env python3
"""Narrow arena descriptor warnings; no lifetime type system."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
with tempfile.TemporaryDirectory(prefix='dyn-owner-warnings-') as temporary:
    project = Path(temporary)
    source = project / 'main.dyn'
    source.write_text('''use "std/mem"
fn main() {
  storage: [64]u8 = []
  original := mem.arena_from_buffer(storage[..])
  duplicate := original
  _ = duplicate
}
''')
    command = [DYN, 'check', str(project), '--no-cache', '--diagnostics', 'json']
    normal = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert normal.returncode == 0, normal.stderr
    reports = [json.loads(line) for line in normal.stderr.splitlines() if line.startswith('{')]
    assert any(r['severity'] == 'warning' and 'copying an arena' in r['message'] for r in reports), normal.stderr
    strict = subprocess.run([*command, '--warnings-as-errors'], capture_output=True, text=True, timeout=30)
    assert strict.returncode == 1 and 'copying an arena' in strict.stderr, strict.stderr
    output = project / 'copy-program'
    built = subprocess.run([DYN, 'build', str(project), '--output', str(output)],
                           capture_output=True, text=True, timeout=120)
    assert built.returncode == 0, built.stderr
    strict_build = subprocess.run([DYN, 'build', str(project), '--warnings-as-errors',
                                   '--output', str(output)], capture_output=True, text=True, timeout=120)
    assert strict_build.returncode == 1, strict_build.stderr
    quiet = subprocess.run([*command, '--no-warnings'], capture_output=True, text=True, timeout=30)
    assert quiet.returncode == 0 and 'copying an arena' not in quiet.stderr, quiet.stderr
    source.write_text('''use "std/mem"
fn main() {
  storage: [64]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  pointer := mem.arena_push(&arena, 1, 1)
  mem.arena_rewind(&arena, 0)
  pointer.* = 42
}
''')
    expired = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert expired.returncode == 1 and 'arena_rewind to zero' in expired.stderr, expired.stderr
    source.write_text('''use "std/mem"
fn main() {
  storage: [64]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  allocation := mem.arena_push_array(&arena, 1, 1, 1)
  pointer := allocation
  mem.arena_reset(&arena)
  pointer.* = 42
}
''')
    helper = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert helper.returncode == 1 and 'after arena_reset' in helper.stderr, helper.stderr
    source.write_text('''use "std/mem"
fn main() {
  created := mem.arena_create(mem.KiB)
  pointer := mem.arena_push(&created, 1, 1)
  pointer.* = 42
  moved := mem.arena_take(&created)
  if #len(created.data) != 0 || created.owns_memory || pointer.* != 42 { #panic("transfer") }
  mem.arena_release(&created)
  if pointer.* != 42 { #panic("old owner") }
  mem.arena_release(&moved)
}
''')
    for release in (False, True):
        output = project / 'program'
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--warnings-as-errors',
                        '--output', str(output), *(['--release'] if release else [])], check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=10)
print('PASS arena copy warning, strict/suppressed modes, and explicit ownership transfer')
