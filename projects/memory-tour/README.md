# Dyn memory tour

Read `main.dyn` from top to bottom, then run it. Each numbered lesson explains
its result; assertions panic if the demonstrated behavior is wrong. The program
uses only the standard library and does not intentionally access expired memory.

From the repository root:

```sh
just all
./build/dyn build projects/memory-tour --output build/memory-tour
./build/memory-tour

# Exercise the same lessons with release code generation.
./build/dyn build projects/memory-tour --release --output build/memory-tour-release
./build/memory-tour-release
```

Expected output ends with `Memory tour passed.` followed by this guide's path.

## The model

Start with two questions: **who supplies the storage, and when does it expire?**
An arena is a cursor over storage. Heap-backed and buffer-backed fixed arenas use
identical allocation calls. Allocating an object advances the cursor; resetting
reclaims the group. An arena does not automatically grow or run object destructors.

| Representation | Meaning |
| --- | --- |
| `[N]T` | An array containing N elements |
| `*T` | A pointer to one element; `pointer.*` dereferences it |
| `[]T` | A borrowed pointer/length view, indexed with `slice[index]` |
| `[]const T` | A view that cannot modify elements through that view |
| `mem.Arena` | Backing slice, cursor and ownership/diagnostic state |

A slice neither owns nor copies its elements. Const does not mean the underlying
storage cannot change through another mutable reference. Copying a struct also
copies its pointer/slice fields, not their referenced data.

## 1. Buffers, pointers and arrays

`buffers_and_objects` starts with a local `[4096]u8` and wraps it using
`arena_from_buffer`. No heap allocation is involved. `player_create` accepts an
arena pointer so exactly the same helper can use heap-backed storage later.

For one object, allocate `#sizeof(Player)` bytes with `#alignof(Player)` alignment,
then cast to `*Player`. For several, allocate count times that size and form
`(#cast(*Player) memory)[..count]`. Forming the slice allocates nothing.

The example uses a small constant count. For external counts, reject
`count > maximum_usize / #sizeof(Player)` before multiplying. Handle a zero count
explicitly as an empty result; a zero-sized arena allocation returns nil.

`arena_push` zeroes bytes. That does not call a constructor or apply custom field
defaults: assign `Player{ ... }` to initialize the object deliberately.

## 2. Heap backing, failure and uninitialized storage

`heap_and_failure` calls `arena_create(4096)`. The small arena descriptor is local;
its backing is supplied by the OS. The deferred release helper checks release
status. Keep the returned arena in place and pass `&created.arena`.

`arena_try_push` reports failure without advancing the cursor. `arena_push`
panics on failure. Fixed arenas never silently fall back to another allocation.
A 4096-byte arena cannot accept an 8192-byte request.

`arena_push_uninit` skips zeroing. Write every byte you will read first. It is
useful when you are about to overwrite the whole destination, not a default to
use everywhere.

## 3. Marks, rewind and reset

`rewind_and_reset` allocates a player, saves a mark, then allocates temporary
bytes. Rewinding to that mark expires only allocations made after it. Resetting
expires all arena allocations while keeping backing capacity for reuse.

With `poison_on_rewind`, reclaimed bytes are overwritten diagnostically. This
costs time proportional to reclaimed bytes and does not make stale pointers safe.
Numeric marks belong to that arena and allocation phase: do not reuse them after
reset/release or apply them to another arena. Nested scopes must unwind in reverse
order. Do not keep the arena descriptor inside the region you rewind.

## 4. Children, retained results and scratch

`children_and_scratch` reserves disjoint subarenas from one root. Creating a child
consumes parent capacity immediately. Resetting a child does not return its region
to the parent. Resetting/releasing the parent invalidates affected children too.

`save_name` makes a scratch copy, trims it, then clones the retained result into
the output arena. Trim alone returns a borrowed view. Returning that scratch view
would be a lifetime bug; returning the output copy is valid until output is reset.
The input may expire after this function because this implementation copies it.
Do not assume every function accepting an arena copies all of its inputs.

`scratch_example` demonstrates `scratch_begin` selecting a candidate that does
not overlap output. `scratch_end` rewinds it. Both candidates still need valid,
exclusively available backing; conflict checking is not an ownership system.

A practical game can have application, level and frame arenas. A server can have
application and request arenas. Reclaim a frame/request only after its consumers,
including asynchronous work, are finished.

## 5. Pools

`pools_and_free_lists` creates two Player slots. A third checked acquisition
returns nil. Releasing one slot permits another acquisition without changing
parent arena usage or invalidating the other live player.

Always initialize an acquired slot. Free slots contain bookkeeping pointers;
recycled slots do not contain a fresh zeroed object. Release expires every pointer
to that object, including copies retained elsewhere. Even if a new object gets
the same address, old references must not be used for it.

Pools are appropriate for bounded objects with independent lifetimes, such as
bullets or connection records. They do not grow automatically. Destroy external
resources owned by an object before returning its slot.

## 6. Free lists

Pool wraps FreeList. A free list links available slots through pointers stored
inside those slots. Acquisition removes the head; release puts a slot back.
Dyn's current release implementation also scans free slots for double frees,
so acquisition is constant-time but release is linear in the number of free slots.

`free_list_from_arena` handles backing allocation/alignment. `free_list_init`
instead borrows a supplied slice: its starting address must be aligned to at least
the greater of requested alignment and internal pointer alignment. A byte array
alone does not promise that alignment; prefer arena-backed creation when unsure.

Slot size includes space for the link and alignment padding. Reserving N objects
can therefore consume more than N times the object size. Pool/free-list metadata
must not be independently copied and mutated, just like arena metadata.

## 7. Growing arenas

`growing_arenas` requests a small block policy, then an allocation larger than
that policy. New blocks are added without moving earlier allocations. One large
allocation still occupies contiguous storage; all blocks together are not one
contiguous slice.

Reset expires objects and retains blocks for reuse. Release frees the backing.
Growth can still fail: use `growing_try_push` for checked failure. `GrowingArena`
is separate from `Arena`; it cannot be passed to an API expecting `*mem.Arena`.

## Rules to keep nearby

- Pass arena pointers. Assignment copies the cursor and ownership flag, not the
  backing. Independent allocations through copies can overlap; copied owners can
  double-release storage. There is no move checker enforcing this for you.
- Never return a pointer/slice into a local array, even through an arena wrapper.
- Bounds/alignment checks do not prove allocation lifetime. Dyn has no borrow
  checker that rejects every use after rewind, reset or pool release.
- Arenas are thread-confined unless you provide synchronization. Do not reclaim
  storage while another thread, callback or GPU operation still needs it.
- Reset does not close files, sockets or native handles. Use matching cleanup
  calls before invalidating their contexts. `defer` schedules cleanup; it does
  not extend any borrowed storage's lifetime.
- SDL and other native libraries may own their own allocations. Their destroy
  operations are separate from Dyn's arena-only heap interface.
- For a bounded output, a destination slice is often simpler than an arena
  argument. `strings.clone_into` accepts stack or arena-backed destination storage.

## Exercises

1. Give `player_create` a stack-backed arena, then a heap-backed one. Its code
   should not change.
2. Change the array count and verify that mutating a sub-slice changes the original.
3. Use a tiny arena and `arena_try_push` to handle exhaustion without a panic.
4. Add a second scratch scope. Check that its rewind preserves earlier output.
5. Increase pool capacity to three. Acquire all slots, release one, then reacquire.
6. Replace the scratch clone in `save_name` with `clone_into` using a local array;
   still clone the final result into output before returning.
7. Sketch which arena would own configuration, a loaded level and one frame's
   render preparation data. Identify the exact event that permits each reset.

Do not test lifetime bugs by deliberately reading expired pointers. Such reads
may appear to work, crash, or corrupt a later object; none is a valid assertion.

For the full API contract, see [memory and ownership](../../docs/memory.md).

## 8. Application lifetimes

The last lesson keeps a pool and a retained result in a persistent arena, while
reusing a separate buffer-backed arena for each request/frame. It copies the one
result that must escape scratch storage, then checks it across sixteen resets.

Use this pattern for server requests, compiler jobs, game frames, or UI rebuilds:

1. Put application state in an arena owned by the application/session.
2. Pass a separate scratch arena into temporary work and reset it afterward.
3. Copy escaping results into their destination lifetime before resetting scratch.
4. Use a pool for equal-sized objects that die independently of their parent arena.
5. Close native resources before resetting/releasing their backing state.

An arena reset does not run native destructors. For concrete native lifetimes,
see [miniaudio cleanup](../miniaudio-example/main.dyn) and
[microui arena storage](../microui-example/main.dyn). Use `defer` in creation order:
register arena release first, then register resource cleanup, so cleanup runs first.
These are explicit ownership decisions; a global arena is not required.

## 9–10. Handles, copies and observable state

`handles_and_observation` uses `std/container/slot_map` for independently deleted
objects. Keep the handle, look up at the point of use, and discard borrowed slot
views before any removal/reinitialization. A stale or foreign-store handle returns
`ok=false`; missing objects are normal, defined states. `copy_into` uses an exhaustive
`CopyStatus` case and caller-owned storage for a value that survives deletion.

Generation backing starts zeroed once, stays alive, and is never cleared again while
old handles exist. Reinitialization advances generations; saturation retires slots.
Handles are process-local references, not persistent IDs or security capabilities.
Do not independently mutate copied map descriptors, forge handles, or write metadata.

`mem.arena_snapshot` and `slots.snapshot` return pointer-free values suitable for
logging or debugger inspection. They report current state, not historical peaks.
`std/profile` records timing in a caller-supplied fixed array; overflow increments
`dropped`. Event names borrow storage, so this example uses static strings. Retained
snapshots remain valid after arena reset. Observation requires exclusive access;
these functions do not synchronize concurrent mutation.
