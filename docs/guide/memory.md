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
| Std | Arenas, typed pushes, `append`, mark/rewind/reset/release, scratch scopes; intrusive free lists in `std/container/list` |
| Application | Lifetime grouping, budgets, synchronization, cleanup order, recovery policy |

The compiler's checks are deliberately narrow. There is no borrow checker,
ownership annotation, reference counting or automatic cleanup, and a clean
`dyn check` does not prove memory safety.

## Arenas

An arena is a `*mem.Arena`: its header lives in its first backing block.
Create it explicitly and pass the pointer directly to arena functions. A nil
pointer is an inactive owner, not a lazily allocating arena.

- `mem.arena_create(block_size)` reserves the first block and adds blocks when
  needed. Earlier allocations do not move. `arena_create(0)` selects the target
  default: 64 GiB per block on 64-bit hosts, 4 MiB on wasm32, and 1 MiB on
  bare-metal targets. Host pages generally cost physical memory when touched;
  wasm32 obtains backed linear memory immediately.
- `mem.arena_create_bounded(block_size, limit)` caps total backing bytes across
  all blocks, including their headers. A zero limit means no cap. A nonzero
  limit smaller than `mem.ArenaHeader` panics. The last block may be smaller
  than the preferred block size to fit the remaining budget.
- Each block reserves `mem.ArenaHeader` (144 bytes) for its header.
  `mem.arena_from_buffer(storage)` also consumes up to 15 initial bytes to
  align the header. To guarantee a given payload capacity with arbitrarily
  aligned caller storage, provide payload size plus
  `mem.ArenaBufferOverhead` (159 bytes). Smaller buffers that cannot hold the
  aligned header panic, including empty buffers.
- Buffer arenas borrow their storage and never add blocks or fall back to OS
  allocation. Reset and rewind preserve this fixed-buffer mode. After release,
  call `arena_from_buffer` again before reusing the buffer as an arena.
- `mem.arena_sub(parent, capacity)` carves out a fixed child; `capacity`
  includes its header, so it is not the child's payload capacity.
- Marks bracket temporary allocations. Rewind releases blocks added after the
  mark and reclaims later allocations in the remaining block. Reset rewinds
  to the empty first block.
- Release returns all owned blocks or clears a borrowed header. It invalidates
  the arena pointer and all its allocations. Release an owner once; a second
  release through a stale owned pointer is invalid. Releasing nil is harmless.

```dyn
root := mem.arena_create(mem.GiB)
defer mem.arena_release(root)
permanent := mem.arena_sub(root, 512 * mem.MiB)
frame := mem.arena_sub(root, 256 * mem.MiB)
scratch := mem.arena_sub(root, 256 * mem.MiB)
```

Keep application state in `permanent`, reset `frame` once per loop or request,
and rewind `scratch` around temporary work.

### Fatal and fallible pushes

The ordinary arena pushes either succeed or stop the program:

- `mem.push(T, arena)` and `mem.push_array(T, arena, count)` return zeroed,
  typed memory; `push_array` checks the size multiplication.
- `mem.push_bytes_uninit(arena, size)` returns bytes without zeroing them.
- `mem.arena_push`, `arena_push_uninit` and `arena_push_array` are the untyped
  forms and return `*u8`.

Owned arenas add backing blocks when a push cannot fit the newest block;
fixed-buffer arenas cannot grow. Owned pushes can fail because of a backing
limit or a failed reservation, and Windows commitment failures panic. Ordinary
push APIs treat exhaustion as fatal. Fallible forms let application code report
exhaustion: `mem.try_push(T, arena)` returns nil and
`mem.try_push_array(T, arena, count)` returns an empty slice on exhaustion or
size overflow. The untyped `mem.arena_try_push` returns an `Allocation` with
an error kind. Failure preserves existing allocations and payload bytes, but
increments the failure counter and may record an observation event.

| Recoverable | Fatal |
| --- | --- |
| `try_push` / `try_push_array` / `arena_try_push` | ordinary arena pushes |

Bounds checks, invalid frees, invalid rewinds and broken layout preconditions
panic everywhere.

### Bounding work that can fail

Std parsers and builders (`strings`, `encoding/json`, `ini` and others) use the fatal pushes. To reject one oversized request and keep running,
give that work its own budget instead of a fallible API:

```dyn
fn handle(server: *mem.Arena, request: []const u8) bool {
  if mem.arena_remaining(server) < RequestBudget {
    return false // reject before starting
  }
  mark := mem.arena_mark(server)
  defer mem.arena_rewind(server, mark)
  scratch := mem.arena_sub(server, RequestBudget)
  // ... parse and respond using scratch ...
  return true
}
```

Size `RequestBudget` from the largest input you accept, checked up front.
The child header consumes part of `RequestBudget`. Inside its payload budget,
`try_push` lets your own code report exhaustion. This precheck deliberately
requires room in the current block; it does not measure all backing that an
owned arena could acquire.

### Partial output on failure

Failure rollback belongs to each function's contract. Some std producers
rewind on failure; others retain partial output. If a caller needs transactional
behavior regardless of the callee, take `mem.arena_mark` before the call and
rewind on failure. Rewinding also releases later backing blocks.

### Appending contiguous data

`mem.append` and `mem.append_many` extend a top allocation in place when
possible. Otherwise they allocate a larger contiguous slice and copy the old
elements. The slice variable is updated; pointers into its previous storage do
not follow it. Earlier independent arena allocations remain at their addresses.

### Other lifetime patterns

- `mem.Frames` holds two arena pointers that alternate each frame, for data
  that must survive exactly one frame. Use `frames_create`, `frame_current`,
  `frame_previous`, `frame_advance` and `frames_release`.
- Individual objects are reused through an intrusive free list: the struct
  carries `free_next`, and `list.free_push` / `list.free_pop` move nodes on and
  off it. Freed nodes stay in the arena until it is reset.

  ```dyn
  spark := list.free_pop(&state.first_free, &nil_particle)
  if spark == &nil_particle {
    spark = mem.push(Particle, arena)
  } else {
    mem.clear(spark)
  }
  spark.life = 30
  list.free_push(&state.first_free, spark)
  ```
- `std/container/slot_map` adds generation-checked handles for objects that are
  deleted independently. See [collections](collections.md).

## Handles

Arenas are the only owners of memory. Everything else that must be cleaned up,
such as files, sockets, child processes, threads, watchers, loaded libraries and
TLS objects, is a handle: a plain value naming an outside resource. Ownership
of handles stays a programmer discipline, with these conventions:

- Each handle has one owner, the variable that will close it. Pass `*T` to
  borrow it; never keep a second copy that might also close it.
- `take(&owner)` (`fs.take`, `process.take`, `net.listener_take`,
  `net.connection_take`) moves the handle out and leaves the
  source closed, so only the result can close it.
- `close(&handle)` for OS resources clears the handle before returning, even
  on failure. Never retry a failed close: the OS may already have reused the descriptor. A second close of
  the same variable is harmless (it reports `InvalidState` or does nothing).
- Close each handle once, usually with `defer` right after a successful open.
- `dyn vet` warns when code copies an arena or a std handle struct (`fs.File`,
  `watch.Watcher`, `process.Child`, `thread.Thread`, `net.Listener`,
  `net.Connection`). Handles that are raw pointers, such as `dynlib.Handle`
  and the TLS types, cannot be tracked; follow the conventions by hand.

## Lifetimes

A slice or pointer borrows storage; copying it never extends the storage's life.

- Rewind invalidates everything pushed after the mark, reset invalidates
  everything in the arena, and release invalidates everything backed by it.
- A stack-backed arena expires with its stack array, and a child arena cannot
  outlive its parent's allocation.
- Share an arena by passing its pointer. The pointer-based API does not enforce
  uncopiability: explicitly copying `arena.*` still copies the header and breaks
  ownership and allocation bookkeeping. Never copy or reconstruct live headers.
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
| `strings.clone` / `join` / `format` | Output arena |
| `strings.split` | Arena for the slice table, and the input for each element |
| JSON `parse` | Arena for nodes and decoded strings; input for number text |
| Text and HTML template `parse` | Output arena, which keeps a copy of the template source |
| Builder `bytes` | Builder storage; changes with mutation |
| CSV, INI and XML scanner items | Input bytes, or reader storage until the next call for streams |
| TAR entries | Archive input, or reader storage until the next call for streams |
| `io.Reader` / `io.Writer` | Callback context and its storage |
| DEFLATE, gzip and zstd decoders | Decoder state, input buffer and history or workspace |

Release native resources before invalidating storage that holds their owners or
callback contexts, and join threads before reclaiming their stacks.

## Inspecting arenas

`mem.arena_snapshot(arena)` returns capacity, used and remaining bytes,
ownership, peak usage and the failed-allocation count as a plain value that
survives reset and release. Peak and failure counters persist across reset and
disappear with the released header. Capacity, used bytes and snapshots walk
the block chain; remaining bytes describe only the newest block, not a
growable arena's total potential budget.

Setting `arena.poison_on_rewind = true` fills reclaimed bytes in the retained
block with `0xDD` on rewind and reset. Later blocks are released. Poisoning
exposes some stale reads at the cost of touching those bytes; it does not make
stale pointers safe.

Attach a caller-owned `std/observe.Log` through `arena.events` to record
allocations, failures and reclamation. The log allocates nothing and counts
dropped events; keep its storage outside the observed arena.

## Cleanup failures

Arena cleanup is infallible at the API boundary: `arena_release` and
`arena_rewind` return no status and panic if an underlying
memory release fails. Dyn has no panic recovery, so callers cannot retry that
failure. Earlier successful block releases remain done. A panic during deferred
cleanup aborts the remaining cleanup.

Thread join is different: returned native errors retain the owner for retry.
Keep the thread, context, and stack alive until a successful join. On Linux,
releasing an owned stack uses `arena_release`, so a memory-release failure
panics instead of returning a join error.

## WebAssembly

On `wasm32-browser` and `wasm32-wasi`, owned arenas get pages through
`memory.grow`. Page splitting, reuse and coalescing live in `std/mem`. Released
memory is reused within the instance but linear memory never shrinks. Any growth
can detach JavaScript typed-array views, so rebuild them after allocating.

### Fallible arena creation

`mem.arena_try_create(block_size)` and `arena_try_create_bounded(block_size, limit)`
return `ArenaCreation` with `arena: *Arena`, `ok`, an error kind and system code.
Failure returns nil and owns no backing; zero block size selects the target
default. `arena_try_push_uninit` provides the ordinary fallible push contract
without initializing returned bytes. Commitment failures return `System` from
fallible pushes, and `arena_try_extend` returns false without advancing the arena.
