#!/usr/bin/env python3
"""Windows reserve/commit ordering for arena headers and chained growth."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/mem"
fn expect(ok: bool) { if !ok { #panic("Windows arena header contract") } }
fn main() {
  for cycle in 0..3 {
    arena := mem.arena_create_bounded(4096, 12288)
    first := mem.arena_push(arena, 3952, 1)
    first.* = 91
    mark := mem.arena_mark(arena)
    second := mem.arena_push(arena, 3952, 1)
    second.* = 72
    expect(mem.arena_snapshot(arena).blocks == 2)
    expect(first.* == 91 && second.* == 72)
    mem.arena_rewind(arena, mark)
    expect(mem.arena_snapshot(arena).blocks == 1 && first.* == 91)
    second = mem.arena_push(arena, 3952, 1)
    expect(second.* == 0 && first.* == 91)
    _ = mem.arena_push(arena, 3952, 1)
    before := mem.arena_snapshot(arena)
    failed := mem.arena_try_push(arena, 1, 1)
    expect(!failed.ok && failed.error == mem.ErrorKind.Capacity)
    after := mem.arena_snapshot(arena)
    expect(after.blocks == 3 && after.used == before.used && first.* == 91)
    mem.arena_reset(arena)
    expect(mem.arena_snapshot(arena).blocks == 1 && mem.arena_used(arena) == 0)
    _ = mem.arena_push(arena, 3952, 1)
    _ = mem.arena_push(arena, 3952, 1)
    mem.arena_release(arena)
  }
}
'''

runner = [] if os.name == 'nt' else ([shutil.which('wine')] if shutil.which('wine') else None)
env = dict(os.environ, WINEDEBUG='-all', WINEDLLOVERRIDES='winemenubuilder.exe=d')
with tempfile.TemporaryDirectory(prefix='dyn-arena-windows-header-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    for mode in ('--debug', '--release'):
        output = project / ('arena-' + mode[2:] + '.exe')
        subprocess.run([DYN, 'build', str(project), '--target', 'x86_64-windows',
                        mode, '--no-cache', '--quiet', '--output', str(output)],
                       cwd=ROOT, check=True, timeout=120)
        if runner is not None:
            subprocess.run([*runner, str(output)], env=env, check=True, timeout=45)
print('PASS Windows arena headers, growth, rewind/reuse, bounded failure (debug/release)' +
      ('; runtime SKIP: Wine unavailable' if runner is None else ''))
