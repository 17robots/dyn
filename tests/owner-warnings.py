#!/usr/bin/env python3
"""dyn vet findings (duplicate imports), silent check and build, and explicit
ownership transfer of an arena handle."""
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
  storage: [64 + mem.ArenaBufferOverhead]u8
  original := mem.arena_from_buffer(storage[..])
  duplicate := original.*
  _ = duplicate
}
''')
    command = [DYN, 'check', str(project), '--no-cache', '--diagnostics', 'json']
    normal = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert normal.returncode == 0, normal.stderr
    for removed in ('--warnings-as-errors', '--no-warnings'):
        rejected = subprocess.run([*command, removed], capture_output=True, text=True, timeout=30)
        assert rejected.returncode == 2, (removed, rejected.stderr)
    (project / 'other.dyn').write_text('use "std/mem" memory\n')
    aliases = subprocess.run([DYN, 'vet', str(project), '--no-cache'], capture_output=True, text=True, timeout=30)
    assert 'imported more than once' not in aliases.stderr, aliases.stderr
    (project / 'other.dyn').write_text('use \"std/mem\" memory\nuse \"std/mem\" another\n')
    aliases = subprocess.run([DYN, 'vet', str(project), '--no-cache'], capture_output=True, text=True, timeout=30)
    assert aliases.returncode == 1 and 'imported more than once' in aliases.stderr, aliases.stderr
    assert 'imported more than once' not in subprocess.run(command, capture_output=True, text=True, timeout=30).stderr
    (project / 'other.dyn').unlink()
    source.write_text('''use "std/mem"
fn main() {
  created := mem.arena_alloc(mem.KiB)
  pointer := mem.push(u8, created)
  pointer.* = 42
  moved := created
  created = nil
  if created != nil || pointer.* != 42 { #panic("transfer") }
  mem.arena_release(created)
  if pointer.* != 42 { #panic("old owner") }
  mem.arena_release(moved)
  moved = nil
  mem.arena_release(moved)
}
''')
    subprocess.run([DYN, 'vet', str(project), '--no-cache', '--quiet'], check=True, timeout=30)
    for release in (False, True):
        output = project / 'program'
        subprocess.run([DYN, 'build', str(project), '--no-cache',
                        '--output', str(output), *(['--release'] if release else [])], check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=10)
print('PASS dyn vet findings, silent check/build and explicit ownership transfer')
