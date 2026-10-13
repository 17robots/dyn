# Memory and ownership

Dyn allocates through arenas only. There is no allocator interface, no
allocation builtin, no garbage collector and no hidden heap use in std. Caller
buffers can be stack arrays, slices carved from an arena, or foreign storage.
Native resources (files, sockets, threads, provider objects) have their own
close or join operation; resetting an arena never closes them.

This follows the lifetime grouping in Ryan Fleury's
[arena article](https://www.dgtlgrove.com/p/untangling-lifetimes-the-arena-allocator)
and the shallow error handling in his
[error article](https://www.dgtlgrove.com/p/the-easiest-way-to-handle-errors).
The names and details are Dyn's own choices.

For complete, tested programs see [memory patterns](memory-patterns.md). For
caller-buffer functions and their error reporting see
[buffer contracts](buffer-contracts.md).

## Who decides what

| Layer | Responsibility |
| --- | --- |
| Compiler | Type parameters for typed pushes, `#sizeof`/`#alignof`, narrow escape and arena-copy checks |
| Std | Arenas, typed pushes, mark/rewind/reset/release, scratch scopes, pools and free lists |
| Application | Lifetime grouping, budgets, synchronization, cleanup order, recovery policy |

The compiler's checks are deliberately narrow. There is no borrow checker,
ownership annotation, reference counting or automatic cleanup, and a clean
`dyn check` does not prove memory safety.

## Arenas

`mem.Arena` either owns reserved address space or borrows a caller buffer. Both
use the same functions.

- `mem.arena_create(capacity)` reserves `capacity` bytes of address space. Pages
  cost memory only once pushes reach them, so reserve generously; a GiB or more
  is normal on 64-bit targets. On wasm32 the memory is backed right away.
- A zero `mem.Arena{}` reserves 64 GiB (4 MiB on wasm32) on its first push, so a
  struct with an arena field works without a constructor.
- `mem.arena_from_buffer(storage)` borrows a fixed buffer, such as a stack array.
- `mem.arena_sub(&parent, capacity)` carves a fixed child out of a parent.
- `mem.arena_mark` and `mem.arena_rewind` bracket temporary allocations;
  `mem.arena_reset` empties the arena.
- `mem.arena_release` frees owned memory, or clears a borrowed arena without
  touching its buffer. Releasing twice does nothing.

```dyn
root := mem.arena_create(mem.GiB)
defer mem.arena_release(&root)
permanent := mem.arena_sub(&root, 512 * mem.MiB)
frame := mem.arena_sub(&root, 256 * mem.MiB)
scratch := mem.arena_sub(&root, 256 * mem.MiB)
```

Keep application state in `permanent`, reset `frame` once per loop or request,
and rewind `scratch` around temporary work.

### Pushes cannot fail

Every arena push either succeeds or stops the program:

- `mem.push(T, &arena)` and `mem.push_array(T, &arena, count)` return zeroed,
  typed memory; `push_array` checks the size multiplication.
- `mem.push_bytes_uninit(&arena, size)` returns bytes without zeroing them.
- `mem.arena_push`, `arena_push_uninit` and `arena_push_array` are the untyped
  forms and return `*u8`.

Running out of an owned arena means the OS is out of memory or address space,
and running out of a fixed one means the budget was wrong. Neither is something
the caller can fix at the call site, so choosing the budget is the only
decision. Code with a strict budget on a fixed arena can use
`mem.arena_try_push`, the one push that reports exhaustion. It returns an
`Allocation`, and failure leaves the arena unchanged.

Bounded growing arenas, free lists and pools keep fallible forms, since running
out of them is an expected outcome:

| Recoverable | Fatal |
| --- | --- |
| `arena_try_push` | every other arena push |
| `growing_push` / `growing_push_uninit` | `growing_push_or_panic` |
| `free_list_alloc` / `pool_acquire` (nil when empty) | `free_list_alloc_or_panic` / `pool_acquire_or_panic` |

Bounds checks, invalid frees, invalid rewinds and broken layout preconditions
panic everywhere.

### Other arena kinds

- `mem.GrowingArena` is a chain of blocks that never move. `growing_create`,
  `growing_create_bounded`, `growing_reset`, `growing_trim` and
  `growing_release` manage it. A zero `GrowingArena{}` has no capacity limit.
  APIs that take `*mem.Arena` always get a contiguous arena, never a chain.
- `mem.Frames` holds two arenas that alternate each frame, for data that must
  survive exactly one frame.
- Pools and free lists reuse fixed-size slots inside an arena. Each slot holds
  an internal link, so its alignment is at least pointer alignment and fewer
  slots may fit than `backing / size` suggests. Releasing a slot does not shrink
  the backing arena.
- `std/container/slot_map` adds generation-checked handles for objects that are
  deleted independently. See [collections](collections.md).

## Lifetimes

A slice or pointer borrows storage; copying it never extends the storage's life.

- Rewind invalidates everything pushed after the mark, reset invalidates
  everything in the arena, and release invalidates everything backed by it.
- A stack-backed arena expires with its stack array, and a child arena cannot
  outlive its parent's allocation.
- Never copy an arena after it has started allocating. Copies share storage but
  keep separate offsets, so their allocations overlap. Pass `*mem.Arena`.
- Arenas are not thread-safe. Synchronize when sharing one.
- Pointers carry no bounds or lifetime. Bounds checks protect slices, and nil and
  alignment checks protect dereferences, but nothing detects use after reset.

### Scratch and retained output

A function that needs temporary memory plus output that outlives the call takes
two arenas: `output` for the result and `scratch` for the work. The scratch
arena must not share backing with the output. `mem.scratch_begin` picks a
scratch arena that does not conflict with a given one, and rejects both the same
arena and any overlapping backing. End scratch scopes in reverse order, and
never return scratch data. When the output size can be bounded, take a caller
slice instead.

A numeric mark is not a generation-checked token: do not reuse marks across
reset or release, or with another arena.

### What each result borrows

| Result | Storage that must stay alive |
| --- | --- |
| String trim, strip and scanner views | Input bytes |
| `strings.clone_into` / `join_into` | Caller destination |
| `strings.clone` / `join` / `format` | Output arena |
| `strings.split` | Arena for the slice table, and the input for each element |
| JSON `parse` | Arena for nodes and decoded strings; input for number text |
| Text and HTML template `parse` | Output arena, which keeps a copy of the template source |
| String-map keys after `put` | Arena that holds the copied keys |
| Builder `bytes` | Builder storage; changes with mutation |
| CSV, INI and XML scanner items | Input bytes, or reader storage until the next call for streams |
| TAR entries | Archive input, or reader storage until the next call for streams |
| `io.Reader` / `io.Writer` | Callback context and its storage |
| DEFLATE, gzip and zstd decoders | Decoder state, input buffer and history or workspace |

Release native resources before invalidating storage that holds their owners or
callback contexts, and join threads before reclaiming their stacks.

## Inspecting arenas

`mem.arena_snapshot(&arena)` returns capacity, used and remaining bytes,
ownership, peak usage and the failed-allocation count as a plain value that
survives reset and release. Peak and failure counters persist across reset and
clear on release.

Setting `arena.poison_on_rewind = true` fills reclaimed bytes with `0xDD` on
rewind and reset. It exposes some stale reads at the cost of touching every
reclaimed byte; it does not make stale pointers safe.

Attach a caller-owned `std/observe.Log` through `arena.events` to record
allocations, failures and reclamation. The log allocates nothing and counts
dropped events; keep its storage outside the observed arena.

## Cleanup failures

Releasing memory or joining a thread can fail at the OS level. On failure the
owner keeps its descriptor so the call can be retried; do not discard it. A
`defer` that ignores a failed release is not proof that cleanup happened.

| Operation | On failure |
| --- | --- |
| Owned arena release | Keeps descriptor and backing; retry on the same arena |
| Growing release | Earlier releases stay done; the remaining chain stays owned |
| Growing trim | Frees only empty blocks; accounting stays accurate |
| Thread join (all platforms) | Keeps the native handle and context; a successful retry clears them |

## WebAssembly

On `wasm32-browser` and `wasm32-wasi`, owned arenas get pages through
`memory.grow`. Page splitting, reuse and coalescing live in `std/mem`. Released
memory is reused within the instance but linear memory never shrinks. Any growth
can detach JavaScript typed-array views, so rebuild them after allocating.
