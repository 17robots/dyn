# Memory and ownership

Dyn-owned heap allocations must come from arenas. Caller buffers can be stack
arrays, slices carved from an arena, or explicitly managed foreign storage.
Private platform mapping functions provide arena backing; they are not a competing
per-object allocation model. Provider-owned objects still require their provider's
close/destroy operation. Arena reset does not close files, sockets, or foreign handles.

The arena-only allocation rule applies to Dyn standard-library APIs. The C compiler
and LSP keep their C allocation strategy; their allocation failures, ownership,
and performance are validated separately. See [compiler architecture](compiler.md)
and [release validation](release/validation.md).

## Shipped arena interface

`std/mem` contains fixed arenas, growing arenas, scratch scopes, pools and free lists.
`mem.Arena` owns heap backing or borrows caller storage:

- `arena_from_buffer` borrows the supplied slice.
- `arena_create(capacity)` returns a checked heap-backed `ArenaResult`.
- `arena_release` frees owned backing or clears a borrowed arena without freeing its buffer.
- `arena_sub` consumes parent storage and returns a child borrowing that region.
- `arena_mark` / `arena_rewind` delimit temporary allocations.
- Reset and rewind invalidate every affected pointer and slice.
- Backing storage must outlive every arena, child, and retained result using it.
- Arenas are thread-confined unless the caller supplies synchronization.
- Do not independently use copies of an arena after allocation starts: copies
  alias storage but maintain independent offsets, allowing allocations to overlap.
- A scratch scope owns its mark and rewind. Scratch results must not escape that scope.

Expected capacity failure uses `arena_try_push`; failure does not advance the arena.
`arena_push` panics on exhaustion. Allocation is zeroed by default; `_uninit` is explicit.
Fixed arenas never silently acquire more heap storage.

```dyn
backing: [4096]u8 = []
root := mem.arena_from_buffer(backing[..])
permanent := mem.arena_sub(&root, 2048)
scratch := mem.arena_sub(&root, 1024)
mark := mem.arena_mark(&scratch)
defer mem.arena_rewind(&scratch, mark)
```

Heap and buffer-backed fixed arenas use the same `Arena` type and the same push,
mark, rewind and reset functions. Keep the arena in its creating scope and pass a
pointer to it. No separate owner wrapper or `take` function is needed:

```dyn
created := mem.arena_create(4096)
if !created.ok { #panic("arena allocation failed") }
defer { _ = mem.arena_release(&created.arena) }
work(&created.arena)
```

`ArenaResult.error` identifies the domain error and `.code` preserves an OS error
when applicable. Zero heap capacity is rejected; zero-capacity borrowed arenas
remain valid. Release is repeatable on the same slot, clears the arena on success,
and preserves it on failure for retry. Calling release on a borrowed arena does
not free its caller-owned storage. Do not change `owns_memory` or the backing slice.

`mem.GrowingArena` remains explicitly separate from a contiguous fixed arena:
`growing_create(block_size)`, `growing_try_push`, `growing_push`, `growing_reset`,
and `growing_release` live in the same `std/mem` module. Blocks never move. Reset
reuses existing blocks; release frees them. Block backing and metadata use the
same fixed-arena implementation. APIs requiring `*mem.Arena` still receive a
contiguous fixed arena, never implicitly switch to chunked storage.

Pool and free-list interfaces remain in `std/mem`. They reuse slots in caller or
arena storage and do not introduce another way to allocate heap memory. Slots
contain an internal pointer link, so effective alignment is the greater of the
requested alignment and pointer alignment; stride is rounded to that alignment.
`pool_init` and `free_list_from_arena` request suitably aligned arena backing.
`free_list_init` borrows caller backing which must already satisfy effective
alignment. Invalid alignment/backing or size overflow panics before linking slots.
Capacity may be smaller than `backing length / requested object size` because
internal link size and padding count toward each slot.

Borrowed and owned fixed arenas have Linux debug/release runtime coverage;
macOS and Windows ownership fixtures cross-link but have not run natively on
this host. Growing arena tests cover alignment, overflow, reuse, and stable
addresses across block growth.

## Buffer and retaining interfaces

A destination `[]u8` means bounded caller storage. It does not imply heap allocation
or require an arena. A `*mem.Arena` argument makes allocation capacity and lifetime
explicit but does not imply that every returned field is copied into that arena.

Every retaining function must document input borrows, copied fields, invalidation,
and failure behavior. On transactional construction failure, rewind only allocations
made by that operation; never invalidate results already exposed elsewhere.

Partial I/O returns progress plus status. `io.read_exact` distinguishes EOF from a
reader that reports success without making progress. Unsupported formatting returns
failure rather than inserting placeholder text. Buffer formatting rollback restores
logical length; it does not promise that unused backing bytes remain unchanged.

Bounds checks protect slice access; nil and alignment checks protect dereference.
Thin pointers do not carry allocation bounds or lifetimes, so these checks cannot
diagnose use after reset.

See [buffer contracts](buffer-contracts.md) for checked allocation/subarena results,
and [collections](collections.md) for builders and maps using explicit arena growth.

## Borrowed results and scratch lifetimes

Storage lifetime and ownership are distinct. A slice is a borrowed pointer/length;
copying it never extends backing storage lifetime. Rewind invalidates allocations
above the saved mark, reset invalidates all arena allocations, and releasing backing
storage invalidates all its borrows. Stack-backed arenas also expire with the stack
array. A child cannot outlive its parent's allocation of its backing slice.

Use one mutable arena cursor per region and pass its pointer. Plain assignment
copies the cursor and ownership flag; it does not create independent storage.
Do not independently allocate through copies or release copied heap arenas.
There is no compiler move feature or public ownership-transfer helper.

`arena.poison_on_rewind = true` enables diagnostic scribbling (`0xDD`) of the
reclaimed region on rewind/reset. Earlier allocations are preserved. This is opt-in
because it makes reclamation linear in reclaimed bytes. It exposes some stale reads;
it cannot make raw pointer use safe or detect all expired borrows. Release still
uses the OS mapping operation. Arena state must not live inside reclaimed storage.

Scratch scopes end in reverse nesting order and cannot escape to retained results.
`scratch_begin` rejects both the same arena object and overlapping backing regions
with the conflict arena. Its candidates must still remain alive and be exclusively
available for scratch use. A numeric mark is not a generation-checked lifetime token:
do not reuse marks across reset/release or with another arena.

For a function that needs scratch plus retained output, accept separate parameters:
`output_arena` owns the result; `scratch_arena` supplies temporary work. Require
disjoint backing if scratch will be reset. Prefer a caller output slice when output
size can be bounded. An arena wrapper can allocate that slice and call the same
buffer implementation. Never return scratch data after ending its scope.

| Interface/result | Storage that must stay alive |
| --- | --- |
| String trim/strip/scanner views | Original input bytes |
| `strings.clone_into` / `join_into` | Caller destination |
| `strings.clone` / `join` | Output arena |
| `strings.split` | Arena for the slice table **and input for each element** |
| JSON `parse` | Arena for nodes/decoded strings; input for number text |
| JSON `just_string` / `just_number` / `add_member` | Arena nodes plus borrowed text/key and child nodes |
| Text/HTML template `parse` | Output arena retains a copy of template source |
| String-map keys after `put` | Arena retains copied keys |
| Builder `bytes` | Builder backing; contents may change with mutation |
| Buffered TAR entry | Archive input |
| TAR/XML stream names/events | Reader storage, until the next advancing call |
| `io.Reader` / `Writer` | Callback context and its backing storage |
| DEFLATE/gzip decoder | Decoder state, input buffer and history buffer |
| zstd decoder | Decoder state, input buffer and static provider workspace |

Resetting an arena does not close files, sockets, databases, TLS handles or threads.
Release native resources before invalidating storage containing their owners or
callback contexts. Join threads before reclaiming their stacks and worker buffers.

## WebAssembly backing

On `wasm32-browser` and `wasm32-wasi`, owned arenas obtain pages through
`memory.grow`. Page allocation, splitting, reuse and coalescing stay in `std/mem`;
the C runtime only exposes the raw growth instruction. Released backing is
reusable within the instance but cannot shrink linear memory. This implementation
is thread-confined. Fixed caller-buffer arenas retain their fixed-capacity behavior.
Any growth can detach JavaScript typed-array views: rebuild those views after
allocation calls, while retaining the numeric pointer only for its arena lifetime.


## Inspecting state and independently deleted objects

`arena_snapshot(&arena)` returns capacity, used/remaining bytes, ownership and
poison configuration, peak usage and failed-allocation count as a pointer-free value.
The snapshot survives arena reset/release. Peak/failure counters persist across reset
and clear when the arena is released/replaced. Call with valid arena state and
exclusive access; no synchronization is added.

Attach a caller-owned `std/observe.Log` through `arena.events` to record allocations,
failures and reclamation. The bounded log allocates nothing and counts dropped events.
Its backing and borrowed labels must outlive recording; keep them outside the observed
arena. See [preview tools](preview-tools.md).

Use `std/container/slot_map` handles when objects need independent deletion and
references must detect slot reuse. Lookup checks backing identity and generation;
`copy_into` returns `Complete`, `Missing` or `Capacity` and copies into caller storage.
Use disjoint output to retain bytes past deletion. `get` still returns a borrowed
view whose lifetime ends at removal/reinitialization. Generation backing must stay
alive and never be cleared while stale handles exist. Public bookkeeping is not a
security boundary. See [collections](collections.md) and the
[agent workflow](agent-guide.md) for exact limits and executable examples.
