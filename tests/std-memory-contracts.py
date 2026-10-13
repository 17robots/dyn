#!/usr/bin/env python3
"""Arena consumers and reuse using real std implementations."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/mem"
use "std/strings"
use "std/encoding/ini"
fn expect(ok: bool) { if !ok { #panic("std memory contract") } }
fn main() {
  storage: [8 * mem.KiB]u8
  arena := mem.arena_from_buffer(storage[..])
  expect(strings.equal(strings.clone(&arena, "retained"), "retained"))
  parts: [2][]const u8 = ["one", "two"]
  expect(strings.equal(strings.join(&arena, parts[..], "/"), "one/two"))
  parsed := ini.parse(&arena, "[window]\nwidth=80\nheight=25\n")
  expect(parsed.ok && #len(parsed.entries) == 3)
  expect(strings.equal(parsed.entries[2].section, "window") && strings.equal(parsed.entries[2].value, "25"))
  before := mem.arena_used(&arena)
  syntax := ini.parse(&arena, "x=1\ninvalid\n")
  expect(!syntax.ok && syntax.error == ini.ErrorKind.Syntax && syntax.error_line == 2)
  expect(mem.arena_used(&arena) == before)
  tiny_storage: [1]u8
  tiny := mem.arena_from_buffer(tiny_storage[..])
  expect(ini.parse(&tiny, "# empty").ok)
  expect(#len(strings.clone(&tiny, "")) == 0)
  expect(mem.arena_used(&tiny) == 0)

  pool := mem.pool_init(&arena, 2, #sizeof(u64), #alignof(u64))
  one := mem.pool_acquire(&pool)
  two := mem.pool_acquire(&pool)
  expect(one != nil && two != nil && mem.pool_acquire(&pool) == nil)
  mem.pool_release(&pool, one)
  again := mem.pool_acquire(&pool)
  expect(again == one && mem.pool_available(&pool) == 0)
  mem.pool_release(&pool, again)
  mem.pool_release(&pool, two)
  expect(mem.pool_available(&pool) == 2)

  growing := mem.growing_create_bounded(128, mem.KiB)
  initial := mem.growing_push_or_panic(&growing, 32, 1)[..32]
  expect(initial[0] == 0 && initial[31] == 0)
  for i in 0..#len(initial) { initial[i] = 165 }
  mem.growing_reset(&growing)
  reused := mem.growing_push_uninit(&growing, 32, 1)
  expect(reused.ok && reused.memory[..32][0] == 165 && reused.memory[..32][31] == 165)
  mem.growing_reset(&growing)
  cleared := mem.growing_push_or_panic(&growing, 32, 1)[..32]
  expect(cleared[0] == 0 && cleared[31] == 0)
  expect(mem.growing_snapshot(&growing).blocks == 1)
  mem.growing_release(&growing)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-std-memory-') as temporary:
    base = Path(temporary)
    for name, source in [('consumers', SOURCE)]:
        project = base / name
        project.mkdir()
        (project / 'main.dyn').write_text(source)
        for release in (False, True):
            output = project / ('release' if release else 'debug')
            subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output),
                            *(['--release'] if release else [])], cwd=ROOT, check=True, timeout=120)
            subprocess.run([str(output)], check=True, timeout=10)
print('PASS std arena consumers, pool reuse, growing zeroing, release/trim (debug/release)')
