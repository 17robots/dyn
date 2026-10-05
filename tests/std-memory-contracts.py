#!/usr/bin/env python3
"""Allocator consumers, reuse, and retryable cleanup using real std implementations."""
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
fn reject(context: rawptr, size: usize, alignment: usize, error: *AllocError) rawptr {
  _ = context _ = size _ = alignment
  error.* = AllocError.System
  return nil
}
fn main() {
  storage: [8 * mem.KiB]u8
  arena := mem.arena_from_buffer(storage[..])
  output := mem.arena_allocator(&arena)
  clone := strings.clone_alloc(output, "retained")
  expect(clone.ok && strings.equal(clone.value, "retained"))
  parts: [2][]const u8 = ["one", "two"]
  joined := strings.join_alloc(output, parts[..], "/")
  expect(joined.ok && strings.equal(joined.value, "one/two"))
  bad := #allocator(nil, &reject)
  failed := strings.clone_alloc(bad, "x")
  expect(!failed.ok && failed.error == strings.ErrorKind.Allocation && failed.allocation_error == AllocError.System)
  expect(strings.clone_alloc(bad, "").ok)
  failed_join := strings.join_alloc(bad, parts[..], "/")
  expect(!failed_join.ok && failed_join.allocation_error == AllocError.System)
  parsed := ini.parse(output, "[window]\nwidth=80\nheight=25\n")
  expect(parsed.ok && #len(parsed.entries) == 3)
  expect(strings.equal(parsed.entries[2].section, "window") && strings.equal(parsed.entries[2].value, "25"))
  before := mem.arena_used(&arena)
  syntax := ini.parse(output, "x=1\ninvalid\n")
  expect(!syntax.ok && syntax.error == ini.ErrorKind.Syntax && syntax.error_line == 2)
  expect(mem.arena_used(&arena) == before)
  oom := ini.parse(bad, "x=1")
  expect(!oom.ok && oom.error == ini.ErrorKind.Allocation && oom.allocation_error == AllocError.System)
  expect(ini.parse(bad, "# empty").ok)
  tiny_storage: [1]u8
  tiny := mem.arena_from_buffer(tiny_storage[..])
  expect(!ini.parse(mem.arena_allocator(&tiny), "x=1").ok)
  expect(mem.arena_used(&tiny) == 0)

  // Arena join retains rollback; generic join explicitly cannot rewind.
  overlap_bytes: [16]u8
  overlap_arena := mem.arena_from_buffer(overlap_bytes[..])
  overlap_bytes[0] = 'a'
  overlap_parts: [1][]const u8 = [overlap_bytes[..1]]
  overlap := strings.join(&overlap_arena, overlap_parts[..], "")
  expect(!overlap.ok && overlap.error == strings.ErrorKind.Overlap)
  expect(mem.arena_used(&overlap_arena) == 0 && overlap_bytes[0] == 'a')
  consumed := strings.join_alloc(mem.arena_allocator(&overlap_arena), overlap_parts[..], "")
  expect(!consumed.ok && consumed.error == strings.ErrorKind.Overlap)
  expect(mem.arena_used(&overlap_arena) == 1 && overlap_bytes[0] == 'a')

  mark := mem.arena_used(&arena)
  invalid := mem.pool_init(&arena, 4, 8, 3)
  expect(!invalid.ok && invalid.error == mem.ErrorKind.InvalidAlignment)
  expect(!mem.pool_init(&arena, #cast(usize) -1, 8, 8).ok)
  expect(!mem.pool_init(&tiny, 4, 8, 8).ok)
  expect(mem.arena_used(&arena) == mark && mem.arena_used(&tiny) == 0)
  pool := mem.pool_init(&arena, 2, #sizeof(u64), #alignof(u64))
  expect(pool.ok)
  one := mem.pool_acquire(&pool.value)
  two := mem.pool_acquire(&pool.value)
  expect(one != nil && two != nil && mem.pool_acquire(&pool.value) == nil)
  mem.pool_release(&pool.value, one)
  again := mem.pool_acquire(&pool.value)
  expect(again == one && mem.pool_available(&pool.value) == 0)
  mem.pool_release(&pool.value, again)
  mem.pool_release(&pool.value, two)
  expect(mem.pool_available(&pool.value) == 2)

  growing := mem.growing_create_bounded(128, mem.KiB)
  handle := mem.growing_allocator(&growing)
  initial := #alloc_slice_or_panic(u8, handle, 32)
  for i in 0..#len(initial) { initial[i] = 165 }
  mem.growing_reset(&growing)
  reused := #alloc_slice_uninit_or_panic(u8, handle, 32)
  expect(reused[0] == 165 && reused[31] == 165)
  mem.growing_reset(&growing)
  cleared := #alloc_slice_or_panic(u8, handle, 32)
  expect(cleared[0] == 0 && cleared[31] == 0)
  expect(mem.growing_snapshot(&growing).blocks == 1)
  expect(mem.growing_release(&growing).ok)
}
'''
CLEANUP = r'''use "./memory" mem
use "./threads" thread
fn expect(ok: bool) { if !ok { #panic("cleanup retry contract") } }
fn worker(context: rawptr) isize { _ = context return 0 }
fn main() {
  owned := mem.arena_create(128)
  expect(owned.ok)
  mem.fail_release(1)
  failed := mem.arena_release(&owned.arena)
  expect(!failed.ok && failed.error == -5 && owned.arena.owns_memory)
  expect(mem.arena_capacity(&owned.arena) == 128)
  expect(mem.arena_release(&owned.arena).ok)
  expect(mem.arena_release(&owned.arena).ok)

  chain := mem.growing_create_bounded(128, 4096)
  _ = mem.growing_push_or_panic(&chain, 128, 8)
  _ = mem.growing_push_or_panic(&chain, 128, 8)
  _ = mem.growing_push_or_panic(&chain, 128, 8)
  before := mem.growing_snapshot(&chain)
  mem.fail_release(2)
  expect(!mem.growing_release(&chain).ok)
  after := mem.growing_snapshot(&chain)
  expect(after.blocks == 2 && after.backing_bytes < before.backing_bytes)
  expect(mem.growing_release(&chain).ok)
  expect(mem.growing_snapshot(&chain).blocks == 0)
  _ = mem.growing_push_or_panic(&chain, 128, 8)
  _ = mem.growing_push_or_panic(&chain, 128, 8)
  _ = mem.growing_push_or_panic(&chain, 128, 8)
  mem.growing_reset(&chain)
  mem.fail_release(2)
  expect(!mem.growing_trim(&chain, 0).ok)
  expect(mem.growing_snapshot(&chain).blocks == 2)
  expect(mem.growing_trim(&chain, 0).ok)
  expect(mem.growing_snapshot(&chain).blocks == 0)

  // Inject spawn failure followed by stack-release failure. No worker runs.
  task := thread.Thread{}
  mem.fail_release(1)
  expect(thread.spawn_with_size(&task, 4096, &worker, nil) == -11)
  expect(mem.arena_capacity(&task.stack_owner) == 4096)
  expect(thread.spawn_with_size(&task, 4096, &worker, nil) == -16)
  mem.fail_release(1)
  expect(thread.join(&task) == -5)
  expect(mem.arena_capacity(&task.stack_owner) == 4096)
  expect(thread.join(&task) == 0)
  expect(mem.arena_capacity(&task.stack_owner) == 0)
  expect(thread.join(&task) == 0)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-std-memory-') as temporary:
    base = Path(temporary)
    for name, source in [('consumers', SOURCE), ('cleanup', CLEANUP)]:
        project = base / name
        project.mkdir()
        (project / 'main.dyn').write_text(source)
        if name == 'cleanup':
            memory = project / 'memory'
            memory.mkdir()
            for filename in ['mem.dyn', 'sizes.dyn', 'allocator.dyn']:
                (memory / filename).write_text((ROOT / 'std/mem' / filename).read_text())
            platform = (ROOT / 'std/mem/linux.dyn').read_text().replace(
                'fn mapping_release(bytes: []u8) isize {',
                '''release_countdown: usize = 0
pub fn fail_release(n: usize) { release_countdown = n }
fn mapping_release(bytes: []u8) isize {
  if release_countdown > 0 {
    release_countdown -= 1
    if release_countdown == 0 { return -5 }
  }''')
            (memory / 'linux.dyn').write_text(platform)
            threads = project / 'threads'
            threads.mkdir()
            thread_source = (ROOT / 'std/thread/thread.dyn').read_text().replace('use "std/mem" mem', 'use "../memory" mem')
            start = thread_source.index('extern fn spawn_raw')
            end = thread_source.index('// Ownership:', start)
            thread_source = thread_source[:start] + '''fn spawn_raw(stack: *u8, size: usize, entry: *fn(rawptr) isize, context: rawptr, tid: *sync.AtomicU32) isize {
  _ = stack _ = size _ = entry _ = context _ = tid
  return -11
}

''' + thread_source[end:]
            (threads / 'thread.dyn').write_text(thread_source)
        for release in (False, True):
            output = project / ('release' if release else 'debug')
            subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output),
                            *(['--release'] if release else [])], cwd=ROOT, check=True, timeout=120)
            subprocess.run([str(output)], check=True, timeout=10)
print('PASS std allocator consumers, pool reuse, growing zeroing, release/trim/spawn/join failure retries (debug/release)')
