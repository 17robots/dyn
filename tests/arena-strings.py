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
  if !strings.equal(greeting, "2 + 3 = 5") { #panic("format") }
  braces := strings.format(arena, "{{{}}}", "x")
  if !strings.equal(braces, "{x}") { #panic("braces") }

  list: strings.List
  strings.list_push(arena, &list, "a")
  strings.list_push_format(arena, &list, "b{}", 2)
  strings.list_push(arena, &list, "")
  if !strings.equal(strings.list_join(arena, &list, ", "), "a, b2, ") { #panic("join") }
  empty: strings.List
  if !strings.equal(strings.list_join(arena, &empty, ","), "") { #panic("empty join") }

  parts := strings.split(arena, "x,,y,", ",")
  if #len(parts) != 4 || !strings.equal(parts[2], "y") || #len(parts[3]) != 0 { #panic("split") }
  if !strings.equal(strings.join(arena, parts, "-"), "x--y-") { #panic("join parts") }
  copied := strings.clone(arena, "copy")
  if !strings.equal(copied, "copy") { #panic("clone") }

  kept := greeting
  mem.frame_advance(frames)
  if mem.frame_previous(frames) != arena { #panic("previous") }
  if !strings.equal(kept, "2 + 3 = 5") { #panic("survives one frame") }
  mem.frame_advance(frames)
  if mem.frame_current(frames) != arena || mem.arena_used(arena) != 0 { #panic("reset") }
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-arena-strings-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    # Misuse and exhaustion panic instead of returning a result.
    for name, body in (('template', 'strings.format(arena, "{} {}", 1)'),
                       ('separator', 'strings.split(arena, "a,b", "")'),
                       ('exhausted', 'strings.format(arena, "{}", "too long for eight")')):
        panic = project / name
        panic.mkdir()
        (panic / 'main.dyn').write_text('use "std/mem" mem\nuse "std/strings" strings\n\nfn main() {\n'
                                        '  storage: [8 + mem.ArenaBufferOverhead]u8\n  arena := mem.arena_from_buffer(storage[..])\n'
                                        f'  _ = {body}\n}}\n')
        subprocess.run([DYN, 'build', str(panic), '--no-cache', '--quiet', '--output', str(panic / 'out')],
                       cwd=ROOT, check=True, timeout=120)
        result = subprocess.run([str(panic / 'out')], capture_output=True, timeout=10)
        assert result.returncode != 0, name
    for release in (False, True):
        output = project / ('release' if release else 'debug')
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet',
                        '--output', str(output), *(['--release'] if release else [])],
                       cwd=ROOT, check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=10)
print('PASS arena formatting, string lists and frame arenas (debug/release)')
