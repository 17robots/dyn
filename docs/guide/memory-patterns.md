# Memory patterns

Choose fixed caller storage or an owned, chained arena according to the
application lifetime and budget. Measure actual use with `arena_used`. A
byte unit makes a budget readable; it does not choose the budget for you. Owned
arenas grow automatically; give `arena_from_source` a source with a limit to
cap their backing.

Every Dyn block in this document is a complete program. The documentation test
builds and runs them in debug and release modes. They use the matching source
compiler and SDK, not necessarily the latest published preview.

## Fixed budgets and array allocation

`mem.push_array(T, arena, count)` checks the multiplication and returns zeroed
`[]T`. Exhausting a fixed arena panics. The buffer below includes 159 bytes
for the 144-byte header and up to 15 bytes of alignment padding, guaranteeing
at least `WorkspaceBytes` of payload capacity.

```dyn
use "std/mem"

const WorkspaceBytes: usize = 4 * mem.KiB
struct Item { value: u64 }

fn main() {
  storage: [WorkspaceBytes + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(storage[..])
  items := mem.push_array<Item>(arena, 10)
  items[9].value = 42
  if items[0].value != 0 || items[9].value != 42 { #panic("array contents") }
  if mem.arena_used(arena) > WorkspaceBytes { #panic("budget") }
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

A function that needs temporary memory takes a scratch arena next to its
output arena, marks scratch on entry and rewinds it on exit. The copied result
survives the rewind; copying a slice descriptor would not.

```dyn
use "std/mem"
use "std/strings"
use "std/bytes"

fn make_label(output: *mem.Arena, scratch: *mem.Arena) []u8 {
  mark := mem.arena_mark(scratch)
  defer mem.arena_rewind(scratch, mark)
  text := strings.clone(scratch, "retained")
  _ = mem.push_bytes(scratch, 16)
  return strings.clone(output, text)
}

fn main() {
  output_storage: [mem.KiB + mem.ArenaBufferOverhead]u8
  scratch_storage: [mem.KiB + mem.ArenaBufferOverhead]u8
  output := mem.arena_from_buffer(output_storage[..])
  scratch := mem.arena_from_buffer(scratch_storage[..])
  label := make_label(output, scratch)
  if mem.arena_used(scratch) != 0 { #panic("scratch contract") }
  mem.zero(scratch.data[mem.ArenaHeader..])
  if !bytes.equal(label, "retained") { #panic("retained output") }
}
```

Scratch must not share backing with the output: rewinding it would take the
result back too. Exhausting either arena panics. No implicit thread-local
scratch storage is installed.

## Bounded text construction

`std/bytes/builder` already provides fixed append, explicit reservation, and
explicit growth within a supplied arena. Reacquire its byte view after mutation.
Capacity failure preserves old content. Builders manipulate bytes; UTF-8 validity
is a separate concern.

```dyn
use builder "std/bytes/builder"
use "std/fail"
use "std/bytes"

fn main() {
  storage: [8]u8
  text := builder.from_buffer(storage[..])
  status: fail.Status
  builder.append(&status, &text, "hello")
  builder.append(&status, &text, " world")
  if status.failure.kind != fail.Kind.Capacity { #panic("capacity") }
  if !bytes.equal(builder.bytes(&text), "hello") { #panic("failure changed text") }
  builder.clear(&text)
  again: fail.Status
  builder.append(&again, &text, "again")
  if again.failed { #panic("reuse") }
}
```

## Formatting into arenas and frames

`strings.format(arena, template, ...)` writes exactly the formatted bytes into
an arena, using the `io.print` template language. `strings.List` collects views
in arena-allocated nodes; `list_join` produces one allocation at the end. For
per-frame work, keep two arenas and swap them each frame, resetting the one
that becomes current, so last frame's data stays readable for one more frame.

```dyn
use "std/mem"
use "std/strings"
use "std/bytes"

fn main() {
  current := mem.arena_alloc(mem.MiB)
  previous := mem.arena_alloc(mem.MiB)
  defer mem.arena_release(current)
  defer mem.arena_release(previous)
  for frame in 0..3 {
    older := previous
    previous = current
    current = older
    mem.arena_reset(current)
    parts: strings.List
    strings.list_push_format(current, &parts, "frame {}", frame)
    strings.list_push(current, &parts, "ok")
    line := strings.list_join(current, &parts, ": ")
    if line.len == 0 { #panic("join") }
  }
}
```

## Bounded growth and reclamation

A source's `limit` caps backing bytes across all blocks, headers included.
The limit is not an RSS measurement. A large allocation can request a block
larger than the preferred size; the last block can be smaller when necessary to
fit the remaining budget. Earlier allocation addresses stay stable.

```dyn
use "std/mem"

fn main() {
  source := mem.pages(16 * mem.KiB)
  source.block_size = mem.KiB
  workspace := mem.arena_from_source(source)
  defer mem.arena_release(workspace)
  prefix := mem.push_bytes(workspace, 8)
  prefix[0] = 42
  mark := mem.arena_mark(workspace)
  _ = mem.push_bytes(workspace, 8 * mem.KiB)
  if workspace.current == workspace { #panic("expected growth") }
  mem.arena_rewind(workspace, mark)
  if workspace.current != workspace || prefix[0] != 42 { #panic("rewind contract") }
  mem.arena_reset(workspace)
  if mem.arena_used(workspace) != 0 { #panic("reset contract") }
}
```

Rewind releases later blocks; reset retains only the empty first block. Neither
operation closes native resources stored in reclaimed memory. Rewind and
release can partially succeed before an OS failure. Successfully released
blocks stay released; the failed release panics rather than returning a
retryable error. Release invalidates the arena pointer itself; do not release it
a second time. OS release failure is not exercised by these examples.

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
- Poisoning aids diagnosis but does not establish memory safety.

## Diagnostics and contracts

Constructors return `*mem.Arena`, with the header stored inside its backing.
Pass this pointer directly rather than taking the address of a local arena
value. Pointer copies alias the same arena; only one owner should release it.
This API does not enforce uncopiability: explicitly copying `arena.*` still
copies the header and breaks allocation bookkeeping. Do not copy live headers.
Moving an address-dependent object remains a programmer obligation. Narrow
compiler diagnostics do not analyze arbitrary user-defined resource owners,
calls, or aggregate copies.

Existing direct reset diagnostics also recognize literal `arena_rewind(..., 0)`.
Other rewind marks, unknown calls, deferred operations, and control-flow joins
remain outside these narrow guarantees. This is not a borrow checker.

`dyn docs MODULE --json` includes optional `contracts` summaries from adjacent
comments labelled `Ownership:`, `Invalidation:`, `Allocation:`, `Failure:`, and
`Thread safety:`. Each summary occupies one line. Full comments remain in
`source_comments`. These are author contracts, not compiler proofs; missing fields
mean unspecified, not safe or allocation-free.

## Typed arena pushes

`mem.push(T, arena)` returns a `*T` that is zeroed and then given the type's field
defaults. `mem.push_array(T, arena, count)` returns a zeroed `[]T`. Both use
the type's size and alignment, so call sites need no casts.
`mem.push_bytes(arena, count)` returns uninitialized `[]u8`, with no
alignment padding, for buffers that are overwritten right away. All three panic when the arena is
full; there is no fallible form.

## Threads

Share nothing by default. Give each thread its own arena, and pass work between
threads under a mutex from `std/sync`. Arenas are not
thread-safe, so a pointer into one thread's arena stays read-only for the others
until the owner is finished with it. A worker returns results by writing into
memory the caller handed it, and the caller reads them after the join.
