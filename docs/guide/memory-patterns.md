# Memory patterns

Fixed arenas are the default starting point. Select a capacity from an application
budget, then measure actual use with `arena_snapshot`. A byte unit makes a budget
readable; it does not choose the budget for you. Growth is an explicit choice.

Every Dyn block in this document is a complete program. The documentation test
builds and runs them in debug and release modes. They use the matching source
compiler and SDK, not necessarily the latest published preview.

## Fixed budgets and array allocation

`mem.push_array(T, &arena, count)` checks the multiplication and returns zeroed
`[]T`. Exhausting the arena panics, so the budget is the only thing to choose.

```dyn
use "std/mem"

const WorkspaceBytes: usize = 4 * mem.KiB
struct Item { value: u64 }

fn main() {
  storage: [WorkspaceBytes]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  items := mem.push_array(Item, &arena, 10)
  items[9].value = 42
  if items[0].value != 0 || items[9].value != 42 { #panic("array contents") }
  snapshot := mem.arena_snapshot(&arena)
  if snapshot.used > WorkspaceBytes { #panic("budget") }
}
```

Array sizes accept integer literals, integer constants, parentheses, and checked
nonnegative arithmetic (`+`, `-`, `*`, `/`, `%`, shifts, and bitwise operators).
Module constants may refer forward to other module constants. Local constants
must precede the declaration using them. Runtime values, function calls, floating
point constants, negative intermediate results, and cycles are rejected. This is
a deliberately limited type-layout expression evaluator, not compile-time execution.
Its recursion limit is 64 and evaluation budget is 4096 expression visits.

## Scratch and retained output

Scratch borrows an arena and records a mark. End scopes in reverse order. Passing
the output arena as a conflict keeps temporary allocations out of its backing.
The copied result survives scratch reset; copying a slice descriptor would not.

```dyn
use "std/mem"
use "std/strings"

fn make_label(output: *mem.Arena, first: *mem.Arena, second: *mem.Arena) []u8 {
  temporary := mem.scratch_begin(first, second, output)
  defer mem.scratch_end(&temporary)
  text := strings.clone(temporary.arena, "retained")
  nested := mem.scratch_begin(first, second, output)
  _ = mem.arena_push(nested.arena, 16, 1)
  mem.scratch_end(&nested)
  return strings.clone(output, text)
}

fn main() {
  output_storage: [mem.KiB]u8 = []
  scratch_storage: [mem.KiB]u8 = []
  output := mem.arena_from_buffer(output_storage[..])
  scratch := mem.arena_from_buffer(scratch_storage[..])
  label := make_label(&output, &output, &scratch)
  if mem.arena_used(&scratch) != 0 { #panic("scratch contract") }
  mem.zero(scratch_storage[..])
  if !strings.equal(label, "retained") { #panic("retained output") }
}
```

Scratch conflicts are programming errors. Both conflicting candidates cause
`scratch_begin` to panic, as does exhausting an arena. No implicit thread-local
scratch storage is installed.

## Bounded text construction

`std/bytes/builder` already provides fixed append, explicit reservation, and
explicit growth within a supplied arena. Reacquire its byte view after mutation.
Capacity failure preserves old content. Builders manipulate bytes; UTF-8 validity
is a separate concern.

```dyn
use "std/bytes/builder" builder
use "std/strings"

fn main() {
  storage: [8]u8 = []
  text := builder.from_buffer(storage[..])
  if builder.append(&text, "hello") != builder.ErrorKind.None { #panic("append") }
  if builder.append(&text, " world") != builder.ErrorKind.Capacity { #panic("capacity") }
  if !strings.equal(builder.bytes(&text), "hello") { #panic("failure changed text") }
  builder.clear(&text)
  if builder.append(&text, "again") != builder.ErrorKind.None { #panic("reuse") }
}
```

## Formatting into arenas and frames

`strings.format(arena, template, ...)` writes exactly the formatted bytes into
an arena, using the `io.print` template language. `strings.List` collects views
in arena-allocated nodes; `list_join` produces one allocation at the end. For
per-frame work, `mem.frames_create` makes two arenas: `frame_advance` swaps them
and resets the new current one, so last frame's data stays readable through
`frame_previous` for one more frame.

```dyn
use "std/mem"
use "std/strings"

fn main() {
  storage := mem.frames_create(mem.MiB)
  frames := &storage
  defer mem.frames_release(frames)
  for frame in 0..3 {
    mem.frame_advance(frames)
    arena := mem.frame_current(frames)
    parts: strings.List
    strings.list_push_format(arena, &parts, "frame {}", frame)
    strings.list_push(arena, &parts, "ok")
    line := strings.list_join(arena, &parts, ": ")
    if #len(line) == 0 { #panic("join") }
  }
}
```

## Explicit growth and retention

`growing_create_bounded` limits requested backing bytes, including headers and
alignment allowance. The limit is not an RSS measurement. A preferred block must
fit in full; choose a block size compatible with the limit. `growing_reset` expires
all payloads but retains blocks. `growing_trim` releases only empty blocks, so its
target may remain unattainable while live allocations exist. Inspect the snapshot.

```dyn
use "std/mem"

fn main() {
  workspace := mem.growing_create_bounded(mem.KiB, 16 * mem.KiB)
  _ = mem.growing_push(&workspace, 8 * mem.KiB, 8)
  mem.growing_reset(&workspace)
  if mem.growing_snapshot(&workspace).backing_bytes == 0 { #panic("reset should retain") }
  mem.growing_trim(&workspace, 0)
  if mem.growing_snapshot(&workspace).backing_bytes != 0 { #panic("trim did not release") }
  mem.growing_release(&workspace)
}
```

Trim/release can partially succeed before an OS failure. Successfully released
blocks stay released; the failed release panics rather than returning a
retryable error. OS release failure is not exercised by these examples.

## Choosing existing mechanisms

- Use `strings.clone` for copied output, wrapping fixed storage in
  `mem.arena_from_buffer` when the copy must live there, and views only while
  their backing remains valid. `strings.split`
  copies the descriptor table but borrows the input bytes.
- Use intrusive free lists and generation handles (`std/container/list`,
  `slot_map`) for independent deletion. Resolve a handle at each use; a stale
  handle gives the stub.
- Hash-table removal unlinks the node but does not reclaim its memory. Reuse
  nodes through a free list, or use an arena per table lifetime.
- Keep thread context, stack, and the Thread descriptor alive and unmoved through
  successful join. Cancellation is an application protocol, not proof of completion.
  A failed join does not authorize reclamation. Linux raw threads do not establish
  libc/pthread TLS; use an appropriate native thread provider for libraries needing it.
- Prefer existing enum outcomes where alternatives matter. Retain useful partial
  I/O counts and native errors. A universal result type is not required.
- Use fixed capacity to exercise exhaustion deterministically. Poisoning and
  counters aid diagnosis but do not establish memory safety. Label snapshots at
  the call site rather than retaining borrowed labels in allocation owners.

## Diagnostics and contracts

Direct copies of known arena descriptors warn; use an address or `arena_take` for
an intentional fixed-arena transfer. Payload addresses survive transfer, but
pointers to the old descriptor do not retarget. Moving an address-dependent
object remains a programmer obligation. This warning does not analyze arbitrary
user-defined resource owners, calls, or aggregate copies.

Existing direct reset diagnostics also recognize literal `arena_rewind(..., 0)`.
Other rewind marks, unknown calls, deferred operations, and control-flow joins
remain outside these narrow guarantees. This is not a borrow checker.

`dyn docs MODULE --json` includes optional `contracts` summaries from adjacent
comments labelled `Ownership:`, `Invalidation:`, `Allocation:`, `Failure:`, and
`Thread safety:`. Each summary occupies one line. Full comments remain in
`source_comments`. These are author contracts, not compiler proofs; missing fields
mean unspecified, not safe or allocation-free.

## Typed arena pushes

`mem.push(T, &arena)` and `mem.push_array(T, &arena, count)` return zeroed `*T`
and `[]T` with the type's size and alignment, so call sites need no casts.
`mem.push_bytes_uninit(&arena, count)` returns uninitialized `[]u8` for buffers
that are overwritten right away. All three panic when the arena is full, like
`mem.arena_push`. Code with a strict budget on a fixed arena can use
`mem.arena_try_push`, the one push that reports exhaustion instead.
