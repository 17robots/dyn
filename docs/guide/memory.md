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
| Std | Arenas, typed pushes, mark/rewind/reset/release; growing arrays in `std/container/array`, intrusive free lists in `std/container/list` |
| Application | Lifetime grouping, budgets, synchronization, cleanup order, recovery policy |

The compiler's checks are deliberately narrow. There is no borrow checker,
ownership annotation, reference counting or automatic cleanup, and a clean
`dyn check` does not prove memory safety.

## Arenas

An arena is a `*mem.Arena`: its header lives in its first backing block.
Create it explicitly and pass the pointer directly to arena functions. A nil
pointer is an inactive owner, not a lazily allocating arena.

The whole API:

| Function | What it does |
| --- | --- |
| `arena_alloc(block_size)` | An arena on OS pages that adds blocks as needed |
| `arena_from_buffer(storage)` | An arena in caller storage that never grows |
| `arena_from_source(source)` | An arena whose blocks come from a `Source` |
| `push(T, arena)` | One zeroed `T` |
| `push_array(T, arena, count)` | `count` zeroed `T`s |
| `push_bytes(arena, count)` | `count` uninitialized bytes, right at the cursor |
| `arena_mark` / `arena_rewind` | Take back everything pushed after a mark |
| `arena_reset` | Take back everything |
| `arena_release` | Return the blocks; the arena is gone |
| `arena_used` | Bytes pushed, padding included, headers excluded |
| `arena_room` | The largest push that cannot run out |

- `mem.arena_alloc(block_size)` reserves the first block and adds blocks when
  needed. Earlier allocations do not move. `arena_alloc(0)` selects the target
  default: 64 GiB per block on 64-bit hosts, 4 MiB on wasm32, and 1 MiB on
  bare-metal targets. Host pages generally cost physical memory when touched;
  wasm32 obtains backed linear memory immediately.
- Each block reserves `mem.ArenaHeader` (144 bytes) for its header.
  `mem.arena_from_buffer(storage)` also consumes up to 15 initial bytes to
  align the header. To guarantee a given payload capacity with arbitrarily
  aligned caller storage, provide payload size plus
  `mem.ArenaBufferOverhead` (159 bytes). Smaller buffers that cannot hold the
  aligned header panic, including empty buffers.
- Buffer arenas borrow their storage and never add blocks or fall back to OS
  allocation. After release, call `arena_from_buffer` again before reusing
  the buffer as an arena.
- Marks bracket temporary allocations. Rewind releases blocks added after the
  mark and reclaims later allocations in the remaining block. Reset rewinds
  to the empty first block.
- Release returns all owned blocks or clears a borrowed header. It invalidates
  the arena pointer and all its allocations. Release an owner once; a second
  release through a stale owned pointer is invalid. Releasing nil is harmless.

### Block sources

A `mem.Source` says where an arena's blocks come from, how big each one is
(`block_size`, zero for the default) and how many backing bytes all of them
may use (`limit`, headers included, zero for no cap):

- `mem.pages(limit)` takes OS pages. `arena_alloc` is
  `arena_from_source(pages(0))` with a block size.
- `mem.within(parent, limit)` pushes each block onto another arena, so a
  child arena lives inside its parent and goes away when the parent rewinds
  past it.
- Your own source sets `take` (return a 16-byte aligned block of at least the
  asked size, or an empty slice) and, optionally, `give` (take one back on
  rewind or release). A static region on a microcontroller or a pool of fixed
  blocks fits here.

```dyn
root := mem.arena_alloc(mem.GiB)
defer mem.arena_release(root)
permanent := mem.arena_from_source(mem.within(root, 512 * mem.MiB))
frame := mem.arena_from_source(mem.within(root, 256 * mem.MiB))
scratch := mem.arena_from_source(mem.within(root, 256 * mem.MiB))
```

Keep application state in `permanent`, reset `frame` once per loop or request,
and rewind `scratch` around temporary work.

### Running out

Every push either succeeds or stops the program, like an index out of range.
A fixed buffer that is full, a limit that is reached, a source with no more
memory and a size that overflows all panic with a message that says which.
There is no fallible push to check: size each arena for its work.

Bounds checks, invalid rewinds and broken layout preconditions panic too.

### Bounding work

To reject one oversized request and keep running, check its size before
starting, then give the work an arena whose limit fits it:

```dyn
fn handle(server: *mem.Arena, request: []const u8) bool {
  if #len(request) > MaxRequest {
    return false // reject before starting
  }
  mark := mem.arena_mark(server)
  defer mem.arena_rewind(server, mark)
  scratch := mem.arena_from_source(mem.within(server, RequestBudget))
  // ... parse and respond using scratch ...
  return true
}
```

Size `RequestBudget` from the largest input you accept. Std parsers and
encoders size their output from the input, so a checked input size bounds
their memory.

### Partial output on failure

Failure rollback belongs to each function's contract. Some std producers
rewind on failure; others retain partial output. If a caller needs transactional
behavior regardless of the callee, take `mem.arena_mark` before the call and
rewind on failure. Rewinding also releases later backing blocks.

### Growing contiguous data

`std/container/array` grows a typed array on an arena: when it fills up it
moves to storage twice the size, and the old storage stays in the arena until
a rewind or reset. `std/bytes/builder` does the same for bytes, except that a
builder whose storage is the arena's newest push grows in place. Pointers into
the old storage do not follow a move. For elements that must never move, use
a chunk list (`std/container/chunk`).

### Other lifetime patterns

- Data that must survive exactly one frame lives in one of two arenas that
  swap each frame: reset the older one and make it current.
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
TLS objects, is a handle: a plain value naming an outside resource, as in C,
Go or Odin. Copy a handle freely; close it once.

- `close(&handle)` for OS resources clears that variable before returning,
  even on failure, so a second close of the same variable does nothing.
  Never retry a failed close: the OS may already have reused the descriptor.
- Other copies keep the old number. Closing one of them too, or using it
  after the close, reaches whatever the system opened next under that number.
  Decide which variable closes the handle, usually with `defer` right after
  a successful open, and pass `*T` to code that only uses it.
- `dyn vet` warns about the obvious case: a variable copied with `=` and
  both copies then passed to the same function, as in
  `copy := file`, `fs.close(&file)`, `fs.close(&copy)`.

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
arena must not share backing with the output. Rewind scratch to a mark taken
on entry, and never return scratch data. When the output size can be bounded,
take a caller slice instead.

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

`mem.arena_used(arena)` counts the bytes pushed across every block, padding
included and headers excluded. To track a peak, read it where the work ends,
before the reset.

Setting `arena.poison_on_rewind = true` fills reclaimed bytes in the retained
block with `0xDD` on rewind and reset. Later blocks are released. Poisoning
exposes some stale reads at the cost of touching those bytes; it does not make
stale pointers safe.

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
