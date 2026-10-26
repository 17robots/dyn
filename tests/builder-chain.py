#!/usr/bin/env python3
"""Builder growth across owned blocks, alias safety and bounded exhaustion."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
ENV = dict(os.environ, DYN_SDK=str(ROOT))
SOURCE = r'''use "std/mem" mem
use "std/bytes/builder" builder
use "std/bytes" bytes
fn require(ok: bool) { if !ok { #panic("builder chain contract") } }
fn moving(block: usize, bounded: bool) {
  arena: *mem.Arena
  if bounded { arena = mem.arena_create_bounded(block, 4096) }
  else { arena = mem.arena_create(block) }
  defer mem.arena_release(arena)
  state: builder.Builder
  require(builder.reserve(&state, arena, 8) == builder.ErrorKind.None)
  require(builder.append(&state, "abcdefgh") == builder.ErrorKind.None)
  old := state.storage
  first := arena.current
  for i in mem.ArenaHeader + 8..#len(first.data) { first.data[i] = 85 }
  mark := mem.arena_mark(arena)
  require(builder.reserve(&state, arena, 64) == builder.ErrorKind.None)
  if &state.storage[0] == &old[0] { #panic("builder move required") }
  require(bytes.equal(builder.bytes(&state), "abcdefgh"))
  require(bytes.equal(old, "abcdefgh"))
  for i in mem.ArenaHeader + 8..#len(first.data) { require(first.data[i] == 85) }
  for i in 0..56 { state.storage[8+i] = #cast(u8, i) }
  state.length = 64
  before := state.storage
  require(builder.append_grow(&state, arena, before) == builder.ErrorKind.None)
  require(state.length == 128 && &state.storage[0] != &before[0])
  require(bytes.equal(state.storage[..64], before) && bytes.equal(state.storage[64..128], before))
  require(bytes.equal(old, "abcdefgh"))
  for i in mem.ArenaHeader + 8..#len(first.data) { require(first.data[i] == 85) }
  mem.arena_rewind(arena, mark)
  require(mem.arena_mark(arena) == mark && mem.arena_snapshot(arena).blocks == 1)
  require(bytes.equal(old, "abcdefgh"))
}
fn current_block() {
  arena := mem.arena_create_bounded(256, 2048)
  defer mem.arena_release(arena)
  guard := mem.push_bytes_uninit(arena, 100)
  mem.fill(guard, 91)
  state: builder.Builder
  require(builder.reserve(&state, arena, 64) == builder.ErrorKind.None)
  require(mem.arena_snapshot(arena).blocks == 2)
  require(builder.append(&state, "seed") == builder.ErrorKind.None)
  previous := &state.storage[0]
  mark := mem.arena_mark(arena)
  require(builder.reserve(&state, arena, 80) == builder.ErrorKind.None)
  require(&state.storage[0] == previous && mem.arena_mark(arena) == mark + 16)
  require(bytes.equal(builder.bytes(&state), "seed"))
  // Another allocation makes the builder non-topmost even in the same block.
  other := mem.push_bytes_uninit(arena, 1)
  other[0] = 37
  require(builder.reserve(&state, arena, 96) == builder.ErrorKind.None)
  require(&state.storage[0] != previous && other[0] == 37)
  for value in guard { require(value == 91) }
  require(bytes.equal(builder.bytes(&state), "seed"))
}
fn failures() {
  backing: [4]u8 = [1, 2, 3, 4]
  state := builder.from_buffer(backing[..])
  require(builder.append(&state, "abc") == builder.ErrorKind.None)
  require(builder.append(&state, "XY") == builder.ErrorKind.Capacity)
  require(state.length == 3 && bytes.equal(builder.bytes(&state), "abc") && backing[3] == 4)
  arena := mem.arena_create(160)
  defer mem.arena_release(arena)
  mark := mem.arena_mark(arena)
  require(builder.reserve(&state, arena, 64) == builder.ErrorKind.Capacity)
  require(builder.append_grow(&state, arena, "z") == builder.ErrorKind.Capacity)
  require(mem.arena_mark(arena) == mark)
  builder.clear(&state)
  require(builder.append(&state, "wxyz") == builder.ErrorKind.None)
  huge := (&backing[0])[..~#cast(usize, 0)]
  require(builder.append_grow(&state, arena, huge) == builder.ErrorKind.Overflow)
  require(mem.arena_mark(arena) == mark && state.length == 4 && bytes.equal(backing[..], "wxyz"))
  builder.clear(&state)
  state.length = 5
  require(builder.reserve(&state, arena, 64) == builder.ErrorKind.InvalidState)
  require(mem.arena_mark(arena) == mark && bytes.equal(backing[..], "wxyz"))
}
fn main() {
  for size in [160, 176, 192] {
    moving(#cast(usize, size), false)
    moving(#cast(usize, size), true)
  }
  current_block()
  failures()
}
'''
PANICS = {
    'bounded': '''arena := mem.arena_create_bounded(160, 320)
  defer mem.arena_release(arena)
  state: builder.Builder
  _ = builder.reserve(&state, arena, 8)
  _ = builder.reserve(&state, arena, 64)''',
    'fixed': '''backing: [16 + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(backing[..])
  arena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader + 16])
  state: builder.Builder
  _ = builder.reserve(&state, arena, 8)
  _ = builder.reserve(&state, arena, 64)''',
}


def build(project, output, mode, env):
    subprocess.run([DYN, 'build', str(project), '--' + mode, '--no-cache', '--quiet',
                    '--output', str(output)], env=env, check=True, timeout=120)


with tempfile.TemporaryDirectory(prefix='dyn-builder-chain-') as temporary:
    root = Path(temporary)
    project = root / 'program'
    project.mkdir()
    baseline = os.environ.get('BUILDER_BASELINE')
    if baseline:
        before = project / 'before'
        before.mkdir()
        (before / 'main.dyn').write_text(Path(baseline).read_text())
        (project / 'main.dyn').write_text(SOURCE.replace('"std/bytes/builder"', '"./before"'))
        output = root / 'baseline'
        build(project, output, 'release', ENV)
        result = subprocess.run([str(output)], capture_output=True, timeout=15)
        assert result.returncode != 0 and b'builder move required' in result.stderr, result
        print('PASS pre-fix negative control: builder incorrectly retained old pointer', flush=True)
        (before / 'main.dyn').unlink()
        before.rmdir()
    for mode in ('debug', 'release'):
        for tree in (False, True):
            env = dict(ENV)
            if tree:
                env['DYN_NO_SSA'] = '1'
            else:
                env.pop('DYN_NO_SSA', None)
            (project / 'main.dyn').write_text(SOURCE)
            output = root / 'builder'
            build(project, output, mode, env)
            subprocess.run([str(output)], env=env, check=True, timeout=15)
            for name, body in PANICS.items():
                (project / 'main.dyn').write_text('use "std/mem" mem\nuse "std/bytes/builder" builder\nfn main() {\n  ' + body + '\n}\n')
                build(project, output, mode, env)
                result = subprocess.run([str(output)], env=env, capture_output=True, timeout=15)
                assert result.returncode != 0 and b'arena exhausted' in result.stderr, (name, mode, tree, result)
            print(f'PASS builder chains {mode} {"tree" if tree else "SSA"}: moves, aliases, canaries, rewind, sticky errors, exhaustion', flush=True)
