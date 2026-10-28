#!/usr/bin/env python3
"""dyn vet findings (arena copies, duplicate imports) and narrow lifetime errors."""
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
    # The compiler reports errors only; suspicious-but-valid code is dyn vet's job.
    normal = subprocess.run(command, capture_output=True, text=True, timeout=30)
    assert normal.returncode == 0 and 'copying an arena' not in normal.stderr, normal.stderr
    vet = subprocess.run([DYN, 'vet', str(project), '--no-cache', '--diagnostics', 'json'],
                         capture_output=True, text=True, timeout=30)
    reports = [json.loads(line) for line in vet.stderr.splitlines() if line.startswith('{')]
    assert vet.returncode == 1, vet.stderr
    assert any(r['severity'] == 'warning' and 'copying an arena' in r['message'] for r in reports), vet.stderr
    output = project / 'copy-program'
    built = subprocess.run([DYN, 'build', str(project), '--output', str(output)],
                           capture_output=True, text=True, timeout=120)
    assert built.returncode == 0 and 'copying an arena' not in built.stderr, built.stderr
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
    source.write_text('''use "std/fs"
use "std/net"
fn main() {
  file := fs.File{}
  copy := file
  _ = copy
  listener := net.Listener{}
  moved := net.listener_take(&listener)
  _ = moved
}
''')
    handles = subprocess.run([DYN, 'vet', str(project), '--no-cache'], capture_output=True, text=True, timeout=30)
    assert handles.returncode == 1 and handles.stderr.count('copying a handle') == 1, handles.stderr
    assert 'main.dyn:5:' in handles.stderr, handles.stderr
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
    subprocess.run([DYN, 'vet', str(project), '--no-cache', '--quiet'], check=True, timeout=30)
    for release in (False, True):
        output = project / 'program'
        subprocess.run([DYN, 'build', str(project), '--no-cache',
                        '--output', str(output), *(['--release'] if release else [])], check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=10)
print('PASS dyn vet findings, silent check/build, lifetime errors and explicit ownership transfer')
