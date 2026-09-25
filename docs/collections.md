# Arena-backed collections

## Byte/string builder

`std/bytes/builder` is a byte-oriented builder usable for UTF-8 strings without imposing
text validation. `Builder{}` starts empty; `from_buffer(storage)` starts with borrowed
stack or arena storage. It never stores an allocator or obtains heap memory implicitly.

```dyn
use "std/bytes/builder"
use "std/mem"

fn main() {
  storage: [256]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  text := builder.Builder{}
  if builder.append_grow(&text, &arena, "hello") != builder.ErrorKind.None {
    #panic("builder capacity")
  }
  _ = builder.bytes(&text)
}
```

- `append` is bounded and allocation-free. `reserve` explicitly reserves exact capacity
  from an arena; `append_grow` grows geometrically, falling back to exact capacity when needed.
- Appending bytes borrowed from the same builder is supported, including during growth.
- Reported failure preserves length, bytes, storage and arena mark. `clear` retains capacity.
- Reacquire byte views after mutation. Old arena buffers remain allocated; growth cannot
  reclaim them without invalidating other arena allocations. Reset/release the owning arena
  only after all builder uses and borrowed views have ended.
- Do not independently mutate copies of a builder sharing storage. No internal locking.

## String-keyed map

`std/container/string_map` maps byte-string keys to `usize` values (IDs, indices, counters).
It uses open addressing, copies keys into the supplied arena, and starts as `Map{}`.

```dyn
use "std/container/string_map" maps
use "std/mem"

fn main() {
  storage: [4096]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  index := maps.Map{}
  if maps.put(&index, &arena, "name", 42) != maps.ErrorKind.None { #panic("map capacity") }
  result := maps.get(&index, "name")
  if !result.found || result.value != 42 { #panic("map lookup") }
}
```

- `put` inserts or updates. Updates allocate nothing. Failed insertion, including a key
  allocation failure after preparing a larger table, preserves both map and arena mark.
- Empty keys and zero values are valid. `get` returns `found` separately from the value.
- `remove` returns whether an entry existed. Removed key bytes remain arena allocations.
- `next` uses a caller cursor starting at zero. Order is unspecified; any mutation invalidates
  iteration. Returned keys borrow the arena and survive table growth, until arena invalidation.
- Tables grow at 75% occupancy. Growth retains previous tables; plan arena capacity for the
  allocation history. Tombstones preserve probe chains after removal. Operations are expected
  constant-time for ordinary keys and worst-case linear; hashing is not collision-attack resistant.
- The arena(s) used by a map must outlive all its uses. Do not mutate public implementation
  fields or independently mutate copies of a live map. No internal locking.


## Slot-map handles and retained copies

`std/container/slot_map` stores fixed-size byte records in caller backing. `init`
borrows disjoint data, generation and occupancy regions. Generation backing starts
zeroed once; subsequent `init` calls advance generations and invalidate all prior
handles/views. Do not clear that backing or let it expire while stale handles exist.
Do not independently mutate map copies or bookkeeping. Operations are thread-confined.

Handles include generation-backing identity, slot index and generation. `get` rejects
empty, out-of-range, stale and foreign-backing handles. A successful `get` returns
borrowed mutable bytes, not a lifetime extension. Reacquire views before use and
finish using them before removal or reinitialization. Handles are process-local,
forgeable tokens, not serializable IDs or security capabilities.

`copy_into` copies a live record into caller output, returning `CopyStatus.Complete`,
`Missing` or `Capacity`. Both failures leave output unchanged. Extra output bytes
remain untouched. Data overlap is supported, but only disjoint output provides an
independent lifetime. Neither source nor destination may corrupt map metadata.
`insert` also supports overlap with record data; input must match slot size exactly.

`remove` zeros bytes and advances the generation. Saturation permanently retires
the slot instead of wrapping. `snapshot` reports capacity, live, available and
retired slots; available + live + retired = capacity. Snapshot values remain valid
after backing expires. Snapshot and insertion scan slots; lookup is constant-time;
copy/removal also cost time proportional to record size.
