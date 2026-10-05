# Memory patterns

Fixed arenas are the default starting point. Select a capacity from an application
budget, then measure actual use with `arena_snapshot`. A byte unit makes a budget
readable; it does not choose the budget for you. Growth is an explicit choice.

Every Dyn block in this document is a complete program. The documentation test
builds and runs them in debug and release modes. They use the matching source
compiler and SDK, not necessarily the latest published preview.

## Fixed budgets and array allocation

`arena_push_array` checks multiplication, alignment, and capacity. The caller
still specifies layout and casts the result. There are no typed allocation
builtins or general generics. A zero-size success returns nil, so only construct a
nonempty slice after checking both success and a nonzero element count.

```dyn
use "std/mem"

const WorkspaceBytes: usize = 4 * mem.KiB
struct Item { value: u64 }

fn main() {
  storage: [WorkspaceBytes]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  count: usize = 10
  allocated := mem.arena_push_array(&arena, count, #sizeof(Item), #alignof(Item))
  if !allocated.ok { #panic("workspace exhausted") }
  items := (#cast(*Item) allocated.memory)[..count]
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

fn make_label(output: *mem.Arena, first: *mem.Arena, second: *mem.Arena) strings.Result {
  temporary := mem.scratch_begin(first, second, output)
  defer mem.scratch_end(&temporary)
  text := strings.clone(temporary.arena, "retained")
  if !text.ok { return text }
  nested := mem.scratch_begin(first, second, output)
  _ = mem.arena_push_or_panic(nested.arena, 16, 1)
  mem.scratch_end(&nested)
  return strings.clone(output, text.value)
}

fn main() {
  output_storage: [mem.KiB]u8 = []
  scratch_storage: [mem.KiB]u8 = []
  output := mem.arena_from_buffer(output_storage[..])
  scratch := mem.arena_from_buffer(scratch_storage[..])
  label := make_label(&output, &output, &scratch)
  if !label.ok || mem.arena_used(&scratch) != 0 { #panic("scratch contract") }
  mem.zero(scratch_storage[..])
  if !strings.equal(label.value, "retained") { #panic("retained output") }
}
```

Scratch conflicts are programming errors, not capacity errors. Both conflicting
candidates cause `scratch_begin` to panic. Ordinary allocation exhaustion uses
fallible allocation results. No implicit thread-local scratch storage is installed.

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
  _ = mem.growing_push_or_panic(&workspace, 8 * mem.KiB, 8)
  mem.growing_reset(&workspace)
  if mem.growing_snapshot(&workspace).backing_bytes == 0 { #panic("reset should retain") }
  if !mem.growing_trim(&workspace, 0).ok { #panic("trim failed") }
  if mem.growing_snapshot(&workspace).backing_bytes != 0 { #panic("trim did not release") }
  if !mem.growing_release(&workspace).ok { #panic("release failed") }
}
```

Trim/release can partially succeed before an OS failure. Successfully released
blocks stay released; unreleased blocks remain owned for retry. Do not discard the
owner on failure. OS release failure is not exercised by these examples.

## Choosing existing mechanisms

- Use `strings.clone_into` for caller-owned output, `strings.clone` for copied
  arena output, and views only while their backing remains valid. `strings.split`
  copies the descriptor table but borrows the input bytes.
- Use pools or slot maps for independent deletion. Reacquire a slot view through
  its handle at each use. `slot_map.lookup` already separates Missing from Present;
  `copy_into` produces retained data when the destination has independent backing.
- String-map removal reuses table positions but does not reclaim copied keys.
  Use an arena per map lifetime, or choose slot/pool storage for bounded churn.
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

## Typed allocation handles

The local source compiler also supports the experimental `Allocator` primitive.
See [Primitive allocator design and implementation](allocator-design.md) for typed
builtins, callbacks, lifetime rules, and validation limits. Explicit arena
operations remain available.
