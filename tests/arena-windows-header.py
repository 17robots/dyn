#!/usr/bin/env python3
"""Windows reserve/commit ordering for arena headers and chained growth."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import private_display  # hides the desktop display; see tests/private_display.py

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/mem"
fn expect(ok: bool) { if !ok { #panic("Windows arena header contract") } }
fn main() {
  for cycle in 0..3 {
    source := mem.pages(12288)
    source.block_size = 4096
    arena := mem.arena_from_source(source)
    first := mem.push_array<u8>(arena, 3952)
    first[0] = 91
    mark := mem.arena_mark(arena)
    second := mem.push_array<u8>(arena, 3952)
    second[0] = 72
    expect(arena.current != arena && arena.current.previous == arena)
    expect(first[0] == 91 && second[0] == 72)
    mem.arena_rewind(arena, mark)
    expect(arena.current == arena && first[0] == 91)
    second = mem.push_array<u8>(arena, 3952)
    expect(second[0] == 0 && first[0] == 91)
    _ = mem.push_array<u8>(arena, 3952)
    expect(arena.backing == 12288 && first[0] == 91)
    mem.arena_reset(arena)
    expect(arena.current == arena && mem.arena_used(arena) == 0)
    _ = mem.push_array<u8>(arena, 3952)
    _ = mem.push_array<u8>(arena, 3952)
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
print('PASS Windows arena headers, growth, rewind/reuse to the limit (debug/release)' +
      ('; runtime SKIP: Wine unavailable' if runner is None else ''))
