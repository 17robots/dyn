#!/usr/bin/env python3
"""Arena pool occupancy and caller-buffer free-list safety (debug/release)."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())
IMPORT = 'use "std/mem" memory\n'
CASES = {
    'reuse': ('''fn main() {
  storage: [40]u64 = []
  bytes := #cast(*u8) &storage[0]
  arena := memory.arena_from_buffer(bytes[..320])
  pool := memory.pool_init(&arena, 17, 16, 8)
  if memory.arena_used(&arena) != 275 || arena.owns_memory { #panic("POOL STORAGE ACCOUNTING") }
  if #len(pool.list.occupied) != 3 { #panic("BITMAP CAPACITY") }
  slots: [17]rawptr = []
  for i in 0..17 {
    slots[i] = memory.pool_acquire(&pool)
    address := #cast(*u8) slots[i]
    payload := address[..16]
    for j in 0..16 { payload[j] = 255 }
  }
  if memory.pool_try_acquire(&pool) != nil || memory.pool_available(&pool) != 0 { #panic("EXHAUSTION") }
  memory.pool_release(&pool, nil)
  for i in 0..17 { memory.pool_release(&pool, slots[i]) }
  if memory.pool_available(&pool) != 17 { #panic("RELEASE COUNT") }
  for i in 0..17 {
    slot := memory.pool_acquire(&pool)
    if slot != slots[16 - i] { #panic("REUSE ORDER") }
  }
  for i in 0..17 { memory.pool_release(&pool, slots[i]) }
  _ = memory.arena_release(&arena)
  storage[0] = 42
  if storage[0] != 42 { #panic("BORROWED STORAGE OWNERSHIP") }

  backing: [8]u64 = []
  buffer := #cast(*u8) &backing[0]
  list := memory.free_list_init(buffer[..64], 8, 8)
  if list.slot_count != 8 || #len(list.occupied) != 0 { #panic("BUFFER CAPACITY CHANGED") }
  borrowed: [8]rawptr = []
  for i in 0..8 { borrowed[i] = memory.free_list_alloc(&list) }
  if memory.free_list_try_alloc(&list) != nil { #panic("BUFFER EXHAUSTION") }
  for i in 0..8 { memory.free_list_free(&list, borrowed[i]) }
  if list.free_count != 8 { #panic("BUFFER RELEASE COUNT") }
  if memory.free_list_alloc(&list) != borrowed[7] { #panic("BUFFER REUSE") }
}
''', None),
    'exact-arena': ('''fn main() {
  storage: [8]u64 = []
  bytes := #cast(*u8) &storage[0]
  arena := memory.arena_from_buffer(bytes[..64])
  pool := memory.pool_init(&arena, 8, 8, 8)
  if memory.arena_used(&arena) != 64 || arena.allocation_failures != 0 { #panic("EXACT ARENA ACCOUNTING") }
  if #len(pool.list.occupied) != 0 { #panic("EXACT ARENA METADATA") }
  slots: [8]rawptr = []
  for i in 0..8 { slots[i] = memory.pool_acquire(&pool) }
  if memory.pool_try_acquire(&pool) != nil { #panic("EXACT ARENA EXHAUSTION") }
  for i in 0..8 { memory.pool_release(&pool, slots[i]) }
  if memory.pool_available(&pool) != 8 { #panic("EXACT ARENA RELEASE") }
  if memory.pool_acquire(&pool) != slots[7] { #panic("EXACT ARENA REUSE") }
}
''', None),
    'exact-arena-double-free': ('''fn main() {
  storage: [8]u64 = []
  bytes := #cast(*u8) &storage[0]
  arena := memory.arena_from_buffer(bytes[..64])
  list := memory.free_list_from_arena(&arena, 8, 8, 8)
  first := memory.free_list_alloc(&list)
  second := memory.free_list_alloc(&list)
  memory.free_list_free(&list, first)
  memory.free_list_free(&list, second)
  memory.free_list_free(&list, first)
}
''', 'free-list double free'),
    'double-free': ('''fn main() {
  storage: [16]u64 = []
  bytes := #cast(*u8) &storage[0]
  arena := memory.arena_from_buffer(bytes[..128])
  pool := memory.pool_init(&arena, 3, 16, 8)
  first := memory.pool_acquire(&pool)
  second := memory.pool_acquire(&pool)
  memory.pool_release(&pool, first)
  memory.pool_release(&pool, second)
  memory.pool_release(&pool, first)
}
''', 'free-list double free'),
    'never-acquired': ('''fn main() {
  storage: [16]u64 = []
  bytes := #cast(*u8) &storage[0]
  arena := memory.arena_from_buffer(bytes[..128])
  list := memory.free_list_from_arena(&arena, 3, 16, 8)
  memory.free_list_free(&list, #cast(rawptr) &list.backing[0])
}
''', 'free-list double free'),
    'foreign-pool': ('''fn main() {
  storage: [32]u64 = []
  bytes := #cast(*u8) &storage[0]
  arena := memory.arena_from_buffer(bytes[..256])
  first := memory.pool_init(&arena, 3, 16, 8)
  second := memory.pool_init(&arena, 3, 16, 8)
  slot := memory.pool_acquire(&second)
  memory.pool_release(&first, slot)
}
''', 'pointer does not belong to free list'),
    'interior-pointer': ('''fn main() {
  storage: [16]u64 = []
  bytes := #cast(*u8) &storage[0]
  arena := memory.arena_from_buffer(bytes[..128])
  pool := memory.pool_init(&arena, 3, 16, 8)
  address := #cast(*u8) memory.pool_acquire(&pool)
  slot := address[..16]
  memory.pool_release(&pool, #cast(rawptr) &slot[1])
}
''', 'pointer does not belong to free list'),
    'buffer-double-free': ('''fn main() {
  storage: [8]u64 = []
  bytes := #cast(*u8) &storage[0]
  list := memory.free_list_init(bytes[..64], 8, 8)
  slot := memory.free_list_alloc(&list)
  memory.free_list_free(&list, slot)
  memory.free_list_free(&list, slot)
}
''', 'free-list double free'),
    'pool-exhausted': ('''fn main() {
  storage: [4]u64 = []
  bytes := #cast(*u8) &storage[0]
  arena := memory.arena_from_buffer(bytes[..32])
  pool := memory.pool_init(&arena, 1, 16, 8)
  _ = memory.pool_acquire(&pool)
  _ = memory.pool_acquire(&pool)
}
''', 'free list exhausted'),
}

with tempfile.TemporaryDirectory(prefix='dyn-pool-regressions-') as temporary:
    root = Path(temporary)
    for name, (source, expected_error) in CASES.items():
        directory = root / name
        directory.mkdir()
        (directory / 'main.dyn').write_text(IMPORT + source)
        for release in (False, True):
            output = directory / ('release' if release else 'debug')
            built = subprocess.run(
                [DYN, 'build', str(directory), '--no-cache', '--jobs', '1',
                 '--output', str(output), *(['--release'] if release else [])],
                capture_output=True, text=True, timeout=60)
            assert built.returncode == 0, (name, release, built.stderr)
            result = subprocess.run([str(output)], capture_output=True,
                                    text=True, timeout=10)
            diagnostic = result.stdout + result.stderr
            if expected_error:
                assert result.returncode != 0 and expected_error in diagnostic, (
                    name, release, result.returncode, diagnostic)
            else:
                assert result.returncode == 0, (name, release, diagnostic)

print('PASS pool ownership, occupancy, exhaustion, reuse and double-free checks '
      '(debug/release), preserving caller-buffer capacity')
