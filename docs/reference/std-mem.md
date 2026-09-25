# std/mem

[Reference index](README.md)

## Storage and lifetime

Arena owns heap backing or borrows caller storage. Reset/rewind/release invalidate affected allocations; pools and free lists recycle slots within backing storage. Buffer-backed arenas never fall back to the heap.

## Failure behavior

Try APIs report capacity/alignment/overflow/state/system failures. Failed arena allocation preserves the cursor; checked APIs may panic.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/json-dom/main.dyn](../../tests/json-dom/main.dyn)
- [tests/memory-runtime/main.dyn](../../tests/memory-runtime/main.dyn)
- [tests/owned-arenas/main.dyn](../../tests/owned-arenas/main.dyn)
- [tests/process-arguments/main.dyn](../../tests/process-arguments/main.dyn)
- [tests/process-platform/main.dyn](../../tests/process-platform/main.dyn)
- [tests/release-native/main.dyn](../../tests/release-native/main.dyn)
- [tests/sdk-api-contracts/main.dyn](../../tests/sdk-api-contracts/main.dyn)
- [tests/sdk-behavior-stress/main.dyn](../../tests/sdk-behavior-stress/main.dyn)
- [tests/sdk-boundaries/main.dyn](../../tests/sdk-boundaries/main.dyn)
- [tests/sdk-buffer-contracts/main.dyn](../../tests/sdk-buffer-contracts/main.dyn)
- [tests/sdk-collections/main.dyn](../../tests/sdk-collections/main.dyn)
- [tests/sdk-data/main.dyn](../../tests/sdk-data/main.dyn)
- [tests/sdk-lifetimes/main.dyn](../../tests/sdk-lifetimes/main.dyn)
- [tests/sdk-mem/main.dyn](../../tests/sdk-mem/main.dyn)
- [tests/sdk-memory-observation/main.dyn](../../tests/sdk-memory-observation/main.dyn)
- [tests/sdk-observe/main.dyn](../../tests/sdk-observe/main.dyn)
- [tests/sdk-pool-alignment/main.dyn](../../tests/sdk-pool-alignment/main.dyn)
- [tests/sdk-process/main.dyn](../../tests/sdk-process/main.dyn)
- [tests/sdk-storage-contracts/main.dyn](../../tests/sdk-storage-contracts/main.dyn)
- [tests/sdk-system/main.dyn](../../tests/sdk-system/main.dyn)
- [tests/sdk-template/main.dyn](../../tests/sdk-template/main.dyn)
- [tests/sdk-tls-native/main.dyn](../../tests/sdk-tls-native/main.dyn)
- [tests/sdk-tls/main.dyn](../../tests/sdk-tls/main.dyn)
- [tests/sdk-zstd/main.dyn](../../tests/sdk-zstd/main.dyn)
- [tests/selfhost-runtime/main.dyn](../../tests/selfhost-runtime/main.dyn)
- [tests/stdlib-app/main.dyn](../../tests/stdlib-app/main.dyn)
- [tests/stdlib-contracts/main.dyn](../../tests/stdlib-contracts/main.dyn)
- [tests/stdlib-mem-extra/main.dyn](../../tests/stdlib-mem-extra/main.dyn)
- [tests/stdlib-os-expanded/main.dyn](../../tests/stdlib-os-expanded/main.dyn)
- [tests/stdlib-process/main.dyn](../../tests/stdlib-process/main.dyn)
- [tests/stdlib-runtime/main.dyn](../../tests/stdlib-runtime/main.dyn)
- [tests/stdlib-str/main.dyn](../../tests/stdlib-str/main.dyn)
- [tests/target-macos-platform/main.dyn](../../tests/target-macos-platform/main.dyn)
- [tests/target-windows-platform/main.dyn](../../tests/target-windows-platform/main.dyn)
- [tests/vendor-packages/abi/main.dyn](../../tests/vendor-packages/abi/main.dyn)
- [tests/vendor-packages/curl/main.dyn](../../tests/vendor-packages/curl/main.dyn)

Reviewed behavioral fixtures: [tests/owned-arenas/main.dyn](../../tests/owned-arenas/main.dyn), [tests/sdk-api-contracts/main.dyn](../../tests/sdk-api-contracts/main.dyn), [tests/sdk-behavior-stress/main.dyn](../../tests/sdk-behavior-stress/main.dyn), [tests/sdk-lifetimes/main.dyn](../../tests/sdk-lifetimes/main.dyn), [tests/sdk-memory-observation/main.dyn](../../tests/sdk-memory-observation/main.dyn), [tests/sdk-pool-alignment/main.dyn](../../tests/sdk-pool-alignment/main.dyn), [tests/sdk-storage-contracts/main.dyn](../../tests/sdk-storage-contracts/main.dyn), [tests/wasm-memory.py](../../tests/wasm-memory.py)

## Declarations and source contracts

## Source: compiler/std/mem/linux.dyn

Target gate: `#target(kernel: linux)`

## Source: compiler/std/mem/macos.dyn

Target gate: `#target(kernel: darwin)`

## Source: compiler/std/mem/mem.dyn

[Source](../../compiler/std/mem/mem.dyn#L9)

```dyn
pub enum ErrorKind { None, InvalidAlignment, Capacity, InvalidState, Overflow, System }
```

[Source](../../compiler/std/mem/mem.dyn#L11)

```dyn
pub struct Allocation {
  error: ErrorKind,
  code: isize,
  memory: *u8,
  size: usize,
  ok: bool,
}
```

[Source](../../compiler/std/mem/mem.dyn#L19)

```dyn
pub struct Arena {
  data: []u8,
  offset: usize,
  // Set only by arena_create; caller buffers are never freed.
  owns_memory: bool,
  // Opt-in diagnostic scribble; does not make expired raw pointers safe.
  poison_on_rewind: bool,
  peak_used: usize,
  allocation_failures: usize,
  // Optional borrowed event sink. Keep it outside this arena and alive until release.
  events: *observe.Log,
  event_resource: u64,
}
```

[Source](../../compiler/std/mem/mem.dyn#L33)

```dyn
pub fn arena_from_buffer(backing: []u8) Arena
```

[Source](../../compiler/std/mem/mem.dyn#L39)

Heap-backed fixed arena. Keep this result in place and pass &result.arena.
Buffer-backed arenas never fall back to heap allocation on exhaustion.

```dyn
pub fn arena_create(capacity: usize) ArenaResult
```

[Source](../../compiler/std/mem/mem.dyn#L45)

```dyn
pub struct Status { error: isize, ok: bool }
```

[Source](../../compiler/std/mem/mem.dyn#L49)

Releases owned backing, or clears a borrowed arena without freeing its storage.
Failure leaves the arena intact; repeating release on the same slot is safe.

```dyn
pub fn arena_release(arena: *Arena) Status
```

[Source](../../compiler/std/mem/mem.dyn#L59)

```dyn
pub fn arena_capacity(arena: *const Arena) usize
```

[Source](../../compiler/std/mem/mem.dyn#L60)

```dyn
pub fn arena_used(arena: *const Arena) usize
```

[Source](../../compiler/std/mem/mem.dyn#L61)

```dyn
pub fn arena_remaining(arena: *const Arena) usize
```

[Source](../../compiler/std/mem/mem.dyn#L62)

```dyn
pub fn arena_mark(arena: *const Arena) usize
```

[Source](../../compiler/std/mem/mem.dyn#L64)

```dyn
pub struct ArenaSnapshot {
  capacity: usize, used: usize, remaining: usize, owns_memory: bool, poison_on_rewind: bool,
  peak_used: usize, allocation_failures: usize,
}
```

[Source](../../compiler/std/mem/mem.dyn#L71)

Allocation-free value snapshot. Contains no borrowed pointers and survives reset/release.
Includes peak usage and allocation failures since initialization. No synchronization.

```dyn
pub fn arena_snapshot(arena: *const Arena) ArenaSnapshot
```

[Source](../../compiler/std/mem/mem.dyn#L80)

```dyn
pub fn arena_reset(arena: *Arena)
```

[Source](../../compiler/std/mem/mem.dyn#L84)

```dyn
pub fn arena_rewind(arena: *Arena, mark: usize)
```

[Source](../../compiler/std/mem/mem.dyn#L133)

```dyn
pub fn arena_try_push(arena: *Arena, size: usize, alignment: usize) Allocation
```

[Source](../../compiler/std/mem/mem.dyn#L137)

```dyn
pub fn arena_try_push_uninit(arena: *Arena, size: usize, alignment: usize) Allocation
```

[Source](../../compiler/std/mem/mem.dyn#L141)

```dyn
pub fn arena_push(arena: *Arena, size: usize, alignment: usize) *u8
```

[Source](../../compiler/std/mem/mem.dyn#L147)

```dyn
pub fn arena_push_uninit(arena: *Arena, size: usize, alignment: usize) *u8
```

[Source](../../compiler/std/mem/mem.dyn#L155)

Returned arena borrows storage consumed from parent. Rewind/reset of parent
invalidates child and all allocations made through it.

```dyn
pub struct ArenaResult { arena: Arena, error: ErrorKind, code: isize, ok: bool }
```

[Source](../../compiler/std/mem/mem.dyn#L156)

```dyn
pub fn arena_try_sub(parent: *Arena, capacity: usize) ArenaResult
```

[Source](../../compiler/std/mem/mem.dyn#L163)

```dyn
pub fn arena_sub(parent: *Arena, capacity: usize) Arena
```

[Source](../../compiler/std/mem/mem.dyn#L169)

```dyn
pub struct Scratch {
  arena: *Arena,
  mark: usize,
  active: bool,
}
```

[Source](../../compiler/std/mem/mem.dyn#L186)

```dyn
pub fn scratch_begin(first: *Arena, second: *Arena, conflict: *const Arena) Scratch
```

[Source](../../compiler/std/mem/mem.dyn#L193)

```dyn
pub fn scratch_end(scratch: *Scratch)
```

[Source](../../compiler/std/mem/mem.dyn#L201)

```dyn
pub struct FreeList {
  backing: []u8,
  slot_size: usize,
  slot_count: usize,
  free_count: usize,
  free_head: *FreeListNode,
}
```

[Source](../../compiler/std/mem/mem.dyn#L227)

Slots include an internal pointer link. Effective alignment is at least pointer
alignment, even for byte-sized objects. Backing must satisfy that alignment;
slot stride is rounded up. Storage is borrowed and must outlive the free list.

```dyn
pub fn free_list_init(backing: []u8, requested_slot_size: usize, alignment: usize) FreeList
```

[Source](../../compiler/std/mem/mem.dyn#L254)

```dyn
pub fn free_list_from_arena(
  arena: *Arena,
  slot_count: usize,
  slot_size: usize,
  alignment: usize,
) FreeList
```

[Source](../../compiler/std/mem/mem.dyn#L272)

```dyn
pub fn free_list_try_alloc(list: *FreeList) rawptr
```

[Source](../../compiler/std/mem/mem.dyn#L280)

```dyn
pub fn free_list_alloc(list: *FreeList) rawptr
```

[Source](../../compiler/std/mem/mem.dyn#L286)

```dyn
pub fn free_list_free(list: *FreeList, memory: rawptr)
```

[Source](../../compiler/std/mem/mem.dyn#L308)

Arena-backed fixed-size object storage. Pool is the ordinary reuse interface;
FreeList remains available when callers need its lower-level accounting.

```dyn
pub struct Pool { list: FreeList }
```

[Source](../../compiler/std/mem/mem.dyn#L310)

```dyn
pub fn pool_init(
  arena: *Arena,
  slot_count: usize,
  slot_size: usize,
  alignment: usize,
) Pool
```

[Source](../../compiler/std/mem/mem.dyn#L319)

```dyn
pub fn pool_capacity(pool: *const Pool) usize
```

[Source](../../compiler/std/mem/mem.dyn#L320)

```dyn
pub fn pool_available(pool: *const Pool) usize
```

[Source](../../compiler/std/mem/mem.dyn#L321)

```dyn
pub fn pool_try_acquire(pool: *Pool) rawptr
```

[Source](../../compiler/std/mem/mem.dyn#L322)

```dyn
pub fn pool_acquire(pool: *Pool) rawptr
```

[Source](../../compiler/std/mem/mem.dyn#L323)

```dyn
pub fn pool_release(pool: *Pool, memory: rawptr)
```

[Source](../../compiler/std/mem/mem.dyn#L325)

```dyn
pub fn copy(destination: []u8, source: []const u8) usize
```

[Source](../../compiler/std/mem/mem.dyn#L335)

```dyn
pub fn move(destination: []u8, source: []const u8) usize
```

[Source](../../compiler/std/mem/mem.dyn#L356)

```dyn
pub fn zero(bytes: []u8)
```

[Source](../../compiler/std/mem/mem.dyn#L364)

```dyn
pub fn compare(left: []const u8, right: []const u8) i32
```

[Source](../../compiler/std/mem/mem.dyn#L381)

Blocks never move. Reset retains them for reuse; release invalidates all borrows.
Thread confined and not independently copyable by convention, like Arena.

```dyn
pub struct GrowingArena { first: *Block, current: *Block, block_size: usize }
```

[Source](../../compiler/std/mem/mem.dyn#L382)

```dyn
pub fn growing_create(block_size: usize) GrowingArena
```

[Source](../../compiler/std/mem/mem.dyn#L384)

```dyn
pub fn growing_try_push(arena: *GrowingArena, size: usize, alignment: usize) Allocation
```

[Source](../../compiler/std/mem/mem.dyn#L422)

```dyn
pub fn growing_push(arena: *GrowingArena, size: usize, alignment: usize) *u8
```

[Source](../../compiler/std/mem/mem.dyn#L428)

```dyn
pub fn growing_reset(arena: *GrowingArena)
```

[Source](../../compiler/std/mem/mem.dyn#L437)

```dyn
pub fn growing_release(arena: *GrowingArena) Status
```

## Source: compiler/std/mem/wasm.dyn

Target gate: `#target(arch: wasm32)`

## Source: compiler/std/mem/windows.dyn

Target gate: `#target(kernel: windows)`
