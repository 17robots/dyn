#!/usr/bin/env python3
"""std/fs names directory entry kinds: a file, a directory and a symlink list
as File, Directory and Symlink on POSIX, and the same code checks for macOS and
Windows."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())

PROGRAM = '''use fs "std/fs"
use io "std/io"
use "std/mem"
fn kind_name(kind: fs.EntryKind) str {
  case kind {
    .File => { return "file" }
    .Directory => { return "directory" }
    .Symlink => { return "symlink" }
    .Other => { return "other" }
    .Unknown => { return "unknown" }
  }
}
fn main() {
  arena := mem.arena_alloc(65536)
  items := fs.list(arena, "fixture") catch { #panic("list") }
  for item in items {
    io.println("{} {}", item.name, kind_name(item.kind))
  }
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-entry-kind-') as directory:
    root = Path(directory)
    (root / 'main.dyn').write_text(PROGRAM)
    fixture = root / 'fixture'
    fixture.mkdir()
    (fixture / 'plain.txt').write_text('x')
    (fixture / 'folder').mkdir()
    (fixture / 'link').symlink_to('plain.txt')
    for target in ('x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows'):
        checked = subprocess.run([DYN, 'check', str(root), '--quiet', '--target', target], capture_output=True, text=True)
        assert checked.returncode == 0, (target, checked.stderr)
    program = root / 'program'
    built = subprocess.run([DYN, 'build', str(root), '--quiet', '--no-cache', '--output', str(program)], capture_output=True, text=True)
    assert built.returncode == 0, built.stderr
    listed = subprocess.run([str(program)], cwd=root, capture_output=True, text=True, timeout=10)
    assert listed.returncode == 0, listed.stderr
    kinds = dict(line.split(' ', 1) for line in listed.stdout.splitlines())
    assert kinds == {'plain.txt': 'file', 'folder': 'directory', 'link': 'symlink'}, kinds
print('PASS fs entry kinds: file, directory and symlink named on POSIX; macOS and Windows check')
