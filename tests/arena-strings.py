#!/usr/bin/env python3
"""Arena formatting, string lists and frame arenas, debug/release."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = '''use "std/mem" mem
use "std/strings" strings

fn main() {
  created := mem.frames_create(4096)
  frames := &created
  defer { mem.frames_release(frames) }

  arena := mem.frame_current(frames)
  greeting := strings.format(arena, "{} + {} = {}", 2, 3, 5)
  if !greeting.ok || !strings.equal(greeting.value, "2 + 3 = 5") { #panic("format") }
  braces := strings.format(arena, "{{{}}}", "x")
  if !strings.equal(braces.value, "{x}") { #panic("braces") }
  bad := strings.format(arena, "{} {}", 1)
  if bad.ok || bad.error != strings.ErrorKind.InvalidInput { #panic("bad template") }

  list: strings.List
  if !strings.list_push(arena, &list, "a") { #panic("push") }
  if !strings.list_push_format(arena, &list, "b{}", 2) { #panic("pushf") }
  if !strings.list_push(arena, &list, "") { #panic("empty") }
  joined := strings.list_join(arena, &list, ", ")
  if !joined.ok || !strings.equal(joined.value, "a, b2, ") { #panic("join") }
  empty: strings.List
  if !strings.equal(strings.list_join(arena, &empty, ",").value, "") { #panic("empty join") }

  kept := greeting.value
  mem.frame_advance(frames)
  if mem.frame_previous(frames) != arena { #panic("previous") }
  if !strings.equal(kept, "2 + 3 = 5") { #panic("survives one frame") }
  mem.frame_advance(frames)
  if mem.frame_current(frames) != arena || mem.arena_used(arena) != 0 { #panic("reset") }

  tiny_storage: [8]u8
  tiny := mem.arena_from_buffer(tiny_storage[..])
  full := strings.format(&tiny, "{}", "too long for eight")
  if full.ok || full.error != strings.ErrorKind.Capacity || mem.arena_used(&tiny) != 0 { #panic("capacity") }
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-arena-strings-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    for release in (False, True):
        output = project / ('release' if release else 'debug')
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet',
                        '--output', str(output), *(['--release'] if release else [])],
                       cwd=ROOT, check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=10)
print('PASS arena formatting, string lists and frame arenas (debug/release)')
