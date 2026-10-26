# Pointer and chained arenas (2026-10-25)

This is a breaking development-SDK migration, not a published preview.

An arena handle is now `*mem.Arena`. Its header lives at the start of its backing
block. Copying a handle borrows the same allocation state; it does not create a
second owner. Explicitly copying `arena.*` still copies the public header and is
invalid ownership practice. The type system does not enforce unique ownership.

## Update callers

```dyn
use "std/mem"

fn main() {
  arena := mem.arena_create(0)
  defer mem.arena_release(arena)
  values := mem.push_array(u64, arena, 4)
  values[0] = 42
}
```

Remove the address operator on a local that already holds the returned pointer.
Retain address operators on ordinary structs, list slices, and array elements.
Replace embedded `Arena` fields with `*Arena` handles and initialize them
explicitly. Nil is an absent handle; it does not allocate on first use.

`arena_create(0)` explicitly selects the target default. The constructor's size
is the preferred backing size of each block, including its header. When a block
fills, an owned arena adds a block. Existing independent allocations do not move.
A growing `mem.append` list can move when it outgrows its block; reacquire its
views. `arena_create_bounded(block_size, limit)` caps total backing, including
all headers. A nonzero limit too small for one header panics.

## Fixed buffers and positions

`arena_from_buffer` consumes `ArenaHeader` bytes plus up to 15 alignment bytes.
Reserve `payload + ArenaBufferOverhead` bytes when arbitrary buffer alignment
must still provide the requested payload capacity. Too-small buffers panic at
construction. These borrowed arenas never chain. Subarena backing likewise
includes its own header.

Marks are positions, starting at `arena_start(arena)`, rather than payload byte
counts starting at zero. Save `arena_mark` before an operation and compare the
same mark after rollback. Use `arena_used` to measure payload and padding use.
Do not overwrite an arena header while constructing overlap or canary fixtures.

Rewind and reset release later owned blocks. Reset retains the first block.
Neither operation preserves views into reclaimed allocations. Releasing an
owned arena frees its header too: do not inspect, reuse, or release that pointer
again. Assign nil to the owner after release when an idempotent outer API needs
that state. Releasing nil is safe. Borrowed storage can be initialized again
with `arena_from_buffer` after its prior use has ended.

The separate `GrowingArena` API is replaced by ordinary chained arenas. For an
explicit ownership handoff, assign the pointer to the new owner and set the old
owner to nil; `arena_take` is removed. Close files and join workers before
reclaiming their storage.

Raw C ABI scratch adapters use `c.string_into` to validate and write into
borrowed fixed buffers without allocating an arena header there. This preserves
existing vendor buffer capacities and recoverable capacity errors. Retained C
strings continue to use the arena-first `c.string_from_bytes`.
