#!/usr/bin/env python3
"""Arena chaining, limits, buffers and exhaustion panics; retain reproductions under build/arena-followup."""
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
SOURCE = r'''use "std/mem"
use "std/io"
fn check(ok: bool, message: []const u8) {
  if !ok { #panic(message) }
}
fn blocks(arena: *const mem.Arena) usize {
  count: usize = 0
  block := arena.current
  for block != nil {
    count += 1
    block = block.previous
  }
  return count
}
fn chain() {
  source := mem.pages(4096)
  source.block_size = 192
  arena := mem.arena_from_source(source)
  alias := arena
  first := mem.push_array<u8>(arena, 31)
  for i in 0..31 { first[i] = #cast(u8, i + 17) }
  mark := mem.arena_mark(arena)
  first_backing := arena.backing
  second := mem.push_array<u8>(alias, 96)
  check(mem.arena_mark(alias) == mem.arena_mark(arena), "aliases share cursor")
  check(blocks(arena) == 2, "tiny arena chains")
  for i in 0..96 { second[i] = 77 }
  third := mem.push_array<u8>(arena, 200)
  check(blocks(arena) == 3, "third block")
  for byte in third { check(byte == 0, "new chain allocation zeroed") }
  for i in 0..31 { check(first[i] == #cast(u8, i + 17), "earlier content stable") }
  mem.arena_rewind(alias, mark)
  check(blocks(arena) == 1 && arena.backing == first_backing, "rewind frees later blocks")
  check(mem.arena_used(arena) == 31 && mem.arena_mark(arena) == mark, "rewind restores position")
  for i in 0..31 { check(first[i] == #cast(u8, i + 17), "rewind retains prefix") }
  arena.poison_on_rewind = true
  mem.arena_reset(arena)
  check(mem.arena_used(arena) == 0 && blocks(arena) == 1, "reset keeps initial block")
  reused := mem.push_array<u8>(arena, 31)
  check(&reused[0] == &first[0], "reset reuses initial payload")
  for byte in reused { check(byte == 0, "reuse zeroes poisoned bytes") }
  mem.arena_release(arena)
}
fn zero_sized() {
  arena := mem.arena_from_source(mem.pages(192))
  before := mem.arena_mark(arena)
  check(mem.push_array<u64>(arena, 0).len == 0 && mem.push_bytes(arena, 0).len == 0, "zero pushes are empty")
  check(mem.arena_mark(arena) == before, "zero pushes take nothing")
  mem.arena_release(arena)
}
fn buffers() {
  storage: [1400]u8
  for offset in 0..16 {
    mem.fill(storage[..], 171)
    arena := mem.arena_from_buffer(storage[16+offset..1300])
    address := #cast(usize, arena)
    begin := #cast(usize, &storage[16+offset])
    check(address % 16 == 0 && address >= begin && address - begin <= 15, "caller header alignment")
    check(mem.arena_used(arena) == 0, "header excluded from used")
    small := mem.push<u8>(arena)
    wide := mem.push<u64>(arena)
    before := mem.arena_mark(arena)
    bytes := mem.push_bytes(arena, 7)
    check(#cast(usize, wide) % 8 == 0 && mem.arena_mark(arena) == before + 7, "payload alignment")
    _ = bytes
    check(small.* == 0 && wide.* == 0, "caller payload zeroed")
    mem.arena_release(arena)
    for i in 0..16+offset { check(storage[i] == 171, "leading caller canary") }
    for i in 1300..1400 { check(storage[i] == 171, "trailing caller canary") }
  }
}
fn followup() {
  source := mem.pages(1024)
  source.block_size = 512
  arena := mem.arena_from_source(source)
  _ = mem.push_bytes(arena, 16)
  check(mem.arena_used(arena) == 16, "used excludes header")
  mem.arena_reset(arena)
  _ = mem.push_bytes(arena, 368)
  _ = mem.push_bytes(arena, 368)
  check(arena.backing == 1024, "exact aligned block fits limit")
  check(mem.arena_used(arena) == 736, "chain used excludes headers")
  mem.arena_release(arena)
  last_source := mem.pages(1000)
  last_source.block_size = 512
  last := mem.arena_from_source(last_source)
  _ = mem.push_bytes(last, 368)
  _ = mem.push_bytes(last, 100)
  check(last.backing == 1000, "smaller final block uses remaining budget")
  check(blocks(last) == 2, "smaller last block chains")
  mem.arena_release(last)
  check(mem.ArenaBufferOverhead == 159, "documented caller overhead")
  backing: [256]u8
  for offset in 0..16 {
    mem.fill(backing[..], 171)
    begin := 16 + offset
    end := begin + 64 + mem.ArenaBufferOverhead
    fixed := mem.arena_from_buffer(backing[begin..end])
    _ = mem.push_bytes(fixed, 64)
    mem.arena_release(fixed)
    for i in 0..begin { check(backing[i] == 171, "overhead leading canary") }
    for i in end..256 { check(backing[i] == 171, "overhead trailing canary") }
  }
}
fn pending_blocks() {
  source := mem.pages(1024)
  source.block_size = 176
  arena := mem.arena_from_source(source)
  defer mem.arena_release(arena)
  live := mem.push_bytes(arena, 8)
  pending := arena.current.data[arena.current.offset..]
  _ = mem.push_bytes(arena, 128)
  check(blocks(arena) == 2, "pending test chains")
  check(mem.arena_overlaps_unallocated(arena, pending), "earlier pending block")
  check(!mem.arena_overlaps_unallocated(arena, live), "earlier live allocation")
  empty: []u8
  check(!mem.arena_overlaps_unallocated(arena, empty), "empty pending input")
  foreign: [8]u8
  check(!mem.arena_overlaps_unallocated(arena, foreign[..]), "foreign pending input")
}
fn main() {
  pending_blocks()
  mem.arena_release(nil)
  default_arena: *mem.Arena = mem.arena_alloc(0)
  check(default_arena != nil && mem.arena_used(default_arena) == 0, "explicit default pointer arena")
  mem.arena_release(default_arena)
  followup()
  chain()
  zero_sized()
  buffers()
  io.println("ARENA CHAIN PASS")
}
'''

# Each program must panic with its message: exhaustion is not recoverable.
PANICS = [
    ('small-limit', 'arena_from_source(mem.pages(1))', 'arena limit cannot hold the arena header'),
    ('bounded', 'arena_from_source(mem.pages(192))\n  _ = mem.push_bytes(arena, 20)\n  _ = mem.push_bytes(arena, 100)', 'arena exhausted: it reached its limit'),
    ('buffer', 'arena_from_buffer(storage[..])\n  _ = mem.push_bytes(arena, 1400)', 'arena exhausted: its buffer is full'),
    ('overflow', 'arena_alloc(0)\n  _ = mem.push_array<u64>(arena, #max(usize))', 'arena size overflow'),
]


def run():
    work = Path(os.environ.get('DYN_ARENA_CHAIN_ARTIFACTS', ROOT / 'build/arena-followup/chain-contracts')).resolve()
    project = work / 'source'
    project.mkdir(parents=True, exist_ok=True)
    (project / 'main.dyn').write_text(SOURCE)
    for name, flags, extra_env in [
        ('debug', [], {}),
        ('release', ['--release', '--opt-level', '3', '--cpu', 'generic'], {}),
        ('forced-tree', [], {'DYN_NO_SSA': '1'}),
    ]:
        output = work / name
        command = [str(DYN), 'build', str(project), '--quiet', '--no-cache', '--output', str(output), *flags]
        env = dict(os.environ, DYN_SDK=str(ROOT), **extra_env)
        built = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        (work / (name + '.build.log')).write_text(built.stdout + built.stderr)
        assert built.returncode == 0, (name, built.returncode, built.stdout, built.stderr)
        result = subprocess.run([str(output)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=20)
        (work / (name + '.run.log')).write_text(result.stdout + result.stderr)
        assert result.returncode == 0 and 'ARENA CHAIN PASS' in result.stdout, (name, result.returncode, result.stdout, result.stderr)
        print('PASS arena chain', name, flush=True)
    for case, opening, message in PANICS:
        (project / 'main.dyn').write_text('use "std/mem"\nfn main() {\n  storage: [512]u8\n  arena := mem.' + opening + '\n  _ = storage\n  _ = arena\n}\n')
        for name, flags, extra_env in [
            ('debug', [], {}),
            ('release', ['--release'], {}),
            ('forced-tree', [], {'DYN_NO_SSA': '1'}),
        ]:
            label = case + '-' + name
            output = work / label
            env = dict(os.environ, DYN_SDK=str(ROOT), **extra_env)
            built = subprocess.run([str(DYN), 'build', str(project), '--quiet', '--no-cache', '--output', str(output), *flags], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
            (work / (label + '.build.log')).write_text(built.stdout + built.stderr)
            assert built.returncode == 0, (label, built.stdout, built.stderr)
            result = subprocess.run([str(output)], capture_output=True, text=True, timeout=20)
            (work / (label + '.run.log')).write_text(result.stdout + result.stderr)
            assert result.returncode == 101 and message in result.stdout + result.stderr, (label, result.returncode, result.stdout, result.stderr)
            print('PASS arena panic', label, flush=True)
    (project / 'main.dyn').write_text(SOURCE)

if __name__ == '__main__':
    run()
