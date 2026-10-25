#!/usr/bin/env python3
"""Bounded pointer-arena contracts; retain reproductions under build/arena-followup."""
import os
from pathlib import Path
import subprocess
import shutil

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
SOURCE = r'''use "std/mem"
use "std/observe"
use "std/io"
fn check(ok: bool, message: []const u8) {
  if !ok { #panic(message) }
}
fn chain() {
  arena := mem.arena_create_bounded(192, 4096)
  events: [64]observe.Event = []
  log := observe.log(events[..])
  arena.events = &log
  arena.event_resource = 91
  alias := arena
  first := mem.push_array(u8, arena, 31)
  for i in 0..31 { first[i] = #cast(u8, i + 17) }
  mark := mem.arena_mark(arena)
  first_snapshot := mem.arena_snapshot(arena)
  second := mem.push_array(u8, alias, 96)
  check(mem.arena_mark(alias) == mem.arena_mark(arena), "aliases share cursor")
  check(mem.arena_snapshot(arena).blocks == 2, "tiny arena chains")
  for i in 0..96 { second[i] = 77 }
  third := mem.push_array(u8, arena, 200)
  check(mem.arena_snapshot(arena).blocks == 3, "third block")
  for byte in third { check(byte == 0, "new chain allocation zeroed") }
  for i in 0..31 { check(first[i] == #cast(u8, i + 17), "earlier content stable") }
  check(!mem.arena_try_extend(arena, &first[0], 31, 1), "old block cannot extend")
  peak := arena.peak_used
  mem.arena_rewind(alias, mark)
  rewound := mem.arena_snapshot(arena)
  check(rewound.blocks == 1 && rewound.capacity == first_snapshot.capacity, "rewind frees later blocks")
  check(rewound.used == 31 && mem.arena_mark(arena) == mark, "rewind restores position")
  check(rewound.peak_used == peak && rewound.allocation_failures == 0, "rewind preserves statistics")
  check(log.count == 4 && events[3].kind == observe.Kind.Reclaimed, "rewind event")
  for i in 0..31 { check(first[i] == #cast(u8, i + 17), "rewind retains prefix") }
  arena.poison_on_rewind = true
  mem.arena_reset(arena)
  check(mem.arena_used(arena) == 0 && mem.arena_snapshot(arena).blocks == 1, "reset keeps initial block")
  reused := mem.push_array(u8, arena, 31)
  check(&reused[0] == &first[0], "reset reuses initial payload")
  for byte in reused { check(byte == 0, "reuse zeroes poisoned bytes") }
  check(log.count == 6, "reset and reuse events")
  for i in 0..log.count { check(events[i].resource == 91, "event resource") }
  snapshot := mem.arena_snapshot(arena)
  mem.arena_release(arena)
  check(snapshot.blocks == 1 && snapshot.used == 31, "snapshot survives release")
  check(log.count == 7 && events[6].kind == observe.Kind.Released, "release event")
}
fn failures() {
  arena := mem.arena_create_bounded(192, 192)
  events: [8]observe.Event = []
  log := observe.log(events[..])
  arena.events = &log
  first := mem.push_array(u8, arena, 20)
  mem.fill(first, 69)
  before := mem.arena_mark(arena)
  capacity := mem.arena_capacity(arena)
  failed := mem.arena_try_push(arena, 100, 1)
  check(!failed.ok && failed.error == mem.ErrorKind.Capacity, "bounded exhaustion")
  check(mem.arena_mark(arena) == before && mem.arena_capacity(arena) == capacity, "failed push preserves storage")
  for byte in first { check(byte == 69, "failed push preserves bytes") }
  invalid := mem.arena_try_push(arena, 1, 3)
  check(!invalid.ok && invalid.error == mem.ErrorKind.InvalidAlignment, "invalid alignment")
  check(arena.allocation_failures == 2 && mem.arena_mark(arena) == before, "failure counter")
  check(log.count == 3 && events[0].kind == observe.Kind.Allocated && events[0].value == 20, "allocation event size")
  check(events[1].kind == observe.Kind.AllocationFailed && events[2].kind == observe.Kind.AllocationFailed, "failure events")
  zero := mem.arena_try_push(arena, 0, 4096)
  check(zero.ok && zero.memory == nil && zero.size == 0, "zero push")
  check(#len(mem.push_array(u64, arena, 0)) == 0 && mem.arena_mark(arena) == before, "typed zero push")
  check(log.count == 3 && arena.allocation_failures == 2, "zero pushes have no events or failures")
  mem.arena_release(arena)
  overflow := mem.arena_create_bounded(192, 4096)
  overflow_mark := mem.arena_mark(overflow)
  too_big := mem.arena_try_push(overflow, ~#cast(usize, 0), 16)
  check(!too_big.ok && too_big.error == mem.ErrorKind.Overflow, "push arithmetic overflow")
  check(mem.arena_mark(overflow) == overflow_mark && mem.arena_snapshot(overflow).blocks == 1, "overflow preserves state")
  mem.arena_release(overflow)
}
fn buffers() {
  storage: [1400]u8 = []
  for offset in 0..16 {
    mem.fill(storage[..], 171)
    arena := mem.arena_from_buffer(storage[16+offset..1300])
    address := #cast(usize, arena)
    begin := #cast(usize, &storage[16+offset])
    check(address % 16 == 0 && address >= begin && address - begin <= 15, "caller header alignment")
    check(mem.arena_used(arena) == 0, "header excluded from used")
    for alignment in [1, 2, 8, 32, 256] {
      pushed := mem.arena_try_push(arena, 7, #cast(usize, alignment))
      check(pushed.ok && #cast(usize, pushed.memory) % #cast(usize, alignment) == 0, "payload over-alignment")
      for byte in pushed.memory[..7] { check(byte == 0, "caller payload zeroed") }
    }
    before := mem.arena_mark(arena)
    failed := mem.arena_try_push(arena, 1400, 1)
    check(!failed.ok && failed.error == mem.ErrorKind.Capacity, "buffer never grows")
    check(mem.arena_mark(arena) == before && mem.arena_snapshot(arena).blocks == 1, "fixed failure unchanged")
    mem.arena_release(arena)
    for i in 0..16+offset { check(storage[i] == 171, "leading caller canary") }
    for i in 1300..1400 { check(storage[i] == 171, "trailing caller canary") }
  }
}
fn followup() {
  arena := mem.arena_create_bounded(512, 1024)
  payload := mem.arena_push(arena, 16, 1)
  snapshot := mem.arena_snapshot(arena)
  check(snapshot.used == 16 && snapshot.peak_used == 16, "peak excludes header")
  check(mem.arena_try_extend(arena, payload, 16, 9), "extend newest")
  check(mem.arena_snapshot(arena).peak_used == 25, "extension peak excludes header")
  mem.arena_reset(arena)
  _ = mem.arena_push(arena, 368, 16)
  exact := mem.arena_try_push(arena, 368, 16)
  check(exact.ok && arena.backing == 1024, "exact aligned block fits limit")
  check(mem.arena_used(arena) == 736 && arena.peak_used == 736, "chain peak excludes headers")
  mem.arena_release(arena)
  last := mem.arena_create_bounded(512, 1000)
  _ = mem.arena_push(last, 368, 1)
  partial := mem.arena_try_push(last, 100, 1)
  check(partial.ok && last.backing == 1000, "smaller final block uses remaining budget")
  check(mem.arena_snapshot(last).blocks == 2, "smaller last block chains")
  mem.arena_release(last)
  check(mem.ArenaBufferOverhead == 159, "documented caller overhead")
  backing: [256]u8 = []
  for offset in 0..16 {
    mem.fill(backing[..], 171)
    begin := 16 + offset
    end := begin + 64 + mem.ArenaBufferOverhead
    fixed := mem.arena_from_buffer(backing[begin..end])
    check(mem.arena_capacity(fixed) >= 64, "overhead guarantees payload")
    pushed := mem.arena_try_push(fixed, 64, 1)
    check(pushed.ok, "guaranteed caller payload fits")
    mem.arena_release(fixed)
    for i in 0..begin { check(backing[i] == 171, "overhead leading canary") }
    for i in end..256 { check(backing[i] == 171, "overhead trailing canary") }
  }
}
fn pending_blocks() {
  arena := mem.arena_create_bounded(176, 1024)
  defer mem.arena_release(arena)
  live := mem.push_bytes_uninit(arena, 8)
  pending := arena.current.data[arena.current.offset..]
  _ = mem.arena_push(arena, 128, 1)
  check(mem.arena_snapshot(arena).blocks == 2, "pending test chains")
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
  default_arena: *mem.Arena = mem.arena_create(0)
  check(default_arena != nil && mem.arena_used(default_arena) == 0, "explicit default pointer arena")
  mem.arena_release(default_arena)
  followup()
  chain()
  failures()
  buffers()
  _ = io.println(io.stdout(), "ARENA CHAIN PASS")
}
'''


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
    panic_source = 'use "std/mem"\nfn main() {\n  _ = mem.arena_create_bounded(1, 1)\n}\n'
    (project / 'main.dyn').write_text(panic_source)
    for name, flags, extra_env in [
        ('small-limit-debug', [], {}),
        ('small-limit-release', ['--release'], {}),
        ('small-limit-forced-tree', [], {'DYN_NO_SSA': '1'}),
    ]:
        output = work / name
        env = dict(os.environ, DYN_SDK=str(ROOT), **extra_env)
        built = subprocess.run([str(DYN), 'build', str(project), '--quiet', '--no-cache', '--output', str(output), *flags], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        (work / (name + '.build.log')).write_text(built.stdout + built.stderr)
        assert built.returncode == 0, (name, built.stdout, built.stderr)
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=20)
        (work / (name + '.run.log')).write_text(result.stdout + result.stderr)
        assert result.returncode == 101 and 'arena backing limit cannot hold the header' in result.stdout + result.stderr, (name, result.returncode, result.stdout, result.stderr)
        print('PASS arena chain', name, flush=True)
    (project / 'main.dyn').write_text(SOURCE)
    baseline = ROOT / 'build/arena-followup/mem.before-followup.dyn'
    if baseline.exists():
        sdk = work / 'baseline-sdk'
        shutil.copytree(ROOT / 'std', sdk / 'std', dirs_exist_ok=True)
        shutil.copyfile(baseline, sdk / 'std/mem/mem.dyn')
        # Compile an existing-API regression so missing new constants cannot
        # masquerade as a successful negative control.
        baseline_source = '''use "std/mem"
fn main() {
  arena := mem.arena_create_bounded(512, 1024)
  _ = mem.arena_push(arena, 16, 1)
  if mem.arena_snapshot(arena).peak_used != 16 { #panic("peak excludes header") }
  mem.arena_release(arena)
}
'''
        (work / 'baseline-source.dyn').write_text(baseline_source)
        (project / 'main.dyn').write_text(baseline_source)
        output = work / 'baseline-negative-control'
        env = dict(os.environ, DYN_SDK=str(sdk))
        built = subprocess.run([str(DYN), 'build', str(project), '--quiet', '--no-cache', '--output', str(output)], cwd=ROOT, env=env, capture_output=True, text=True, timeout=120)
        (work / 'baseline.build.log').write_text(built.stdout + built.stderr)
        assert built.returncode == 0, (built.stdout, built.stderr)
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=20)
        (work / 'baseline.run.log').write_text(result.stdout + result.stderr)
        assert result.returncode == 101 and 'peak excludes header' in result.stdout + result.stderr, (result.returncode, result.stdout, result.stderr)
        print('PASS baseline negative control: pre-fix peak includes header', flush=True)
        (project / 'main.dyn').write_text(SOURCE)


if __name__ == '__main__':
    run()
