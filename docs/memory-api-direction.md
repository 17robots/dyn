# Arena-first memory APIs

This is the current local-source policy, not a published SDK release. It supersedes
the initial allocator builtin names. The language supplies typed allocation;
concrete owners and application code decide lifetimes and failure policy.

## Compiler, std, and application responsibilities

| Layer | Responsibility |
| --- | --- |
| Compiler | `Allocator`, known callback construction, typed pointer/slice results, checked sizing, default zeroing, explicit panic forms, tooling |
| Std | Fixed and explicitly growing arenas, mark/rewind/reset/release, scratch scopes, pools/free lists, adapters, domain-specific errors |
| Application | Lifetime grouping, capacity budgets, synchronization, cleanup order, recovery policy |
| Documentation and tests | Borrow/invalidation contracts, failure side effects, examples and fault-injected cleanup checks |

Existing direct local escape, owner-copy, and reset checks remain narrow. There is
no new wrapper tracing, ownership annotation language, borrow checker, GC, ARC,
automatic cleanup, or async framework. A successful compiler check does not prove
memory safety. `Allocator` is a borrowed allocation interface, not an owner.

Organize data by lifetime first: application state, document/session state,
request/frame state, and temporary scratch. Fixed arenas are the recommended
starting point. Explicit growing arenas provide stable payload addresses with a
caller-selected backing limit and deliberate reset/trim policy. Pools/free lists
reuse individual slots inside a region; releasing a slot does not shrink its
backing arena. Use slot-map generation handles when references can survive deletion.
A handle validity check does not keep a subsequently acquired raw view alive.

This is our application of the lifetime-grouping ideas in Ryan Fleury's
[arena article](https://www.dgtlgrove.com/p/untangling-lifetimes-the-arena-allocator)
and the shallow, explicit failure handling in his
[error article](https://www.dgtlgrove.com/p/the-easiest-way-to-handle-errors).
The primitive handle, fixed-by-default guidance, and exact names are Dyn design
choices, not claims that he endorses this API.

## Failure policy and replacements

Recoverable allocation uses ordinary names. `_or_panic` means allocation failure
is fatal through Dyn's existing panic/defer machinery. `_uninit` is before that
suffix. Select panic when the caller has established a sufficient budget or has
chosen termination as its policy; it is not a proof that allocation cannot fail.

| Previous local spelling | Replacement preserving behavior |
| --- | --- |
| `#try_alloc(T, a)` | `#alloc(T, a)` |
| `#alloc(T, a)` | `#alloc_or_panic(T, a)` |
| `#try_alloc_slice(T, a, n)` | `#alloc_slice(T, a, n)` |
| `#alloc_slice(T, a, n)` | `#alloc_slice_or_panic(T, a, n)` |
| `#try_alloc_uninit` / `#try_alloc_slice_uninit` | `#alloc_uninit` / `#alloc_slice_uninit` |
| `#alloc_uninit` / `#alloc_slice_uninit` | `#alloc_uninit_or_panic` / `#alloc_slice_uninit_or_panic` |
| `arena_try_push` / `arena_try_push_uninit` | `arena_push` / `arena_push_uninit` |
| `arena_push` / `arena_push_uninit` | `arena_push_or_panic` / `arena_push_uninit_or_panic` |
| `arena_try_push_array` | `arena_push_array` |
| `arena_try_sub` / `arena_sub` | `arena_sub` / `arena_sub_or_panic` |
| `growing_try_push` / `growing_push` | `growing_push` / `growing_push_or_panic` |
| `free_list_try_alloc` / `free_list_alloc` | `free_list_alloc` / `free_list_alloc_or_panic` |
| `pool_try_acquire` / `pool_acquire` | `pool_acquire` / `pool_acquire_or_panic` |
| `free_list_from_arena` / `pool_init` | `free_list_from_arena_or_panic` / `pool_init_or_panic` |

The new ordinary `free_list_from_arena` and `pool_init` return their own result
structures. Layout/capacity failure leaves the fixed arena offset unchanged.
Pool/free-list acquisition returns nil on exhaustion, avoiding a needless error
category for a single expected outcome. Typed builtins retain `#AllocResult`
with `value`, `error`, and `ok`; this is not a universal std result protocol.

These are simultaneous replacements: do not apply the table sequentially and
rename a newly migrated fallible call into a panic call. Old `try_` names are not
compatibility aliases. Update the compiler, grammar, std, and consumers together.

The suffix convention covers selected recoverable operations, not every possible
panic in a function body. Bounds checks, invalid free/double-free, invalid rewind,
and violated layout preconditions can still panic. `free_list_init` constructs a
view over caller-supplied, correctly aligned backing and retains those validation
panics. No panic-effect type system is introduced. Filesystem/network operations
retain their own status/native errors. Missing lookup values and iterator end
remain normal outcomes. Wrappers are added where useful, not in pairs everywhere.

## Output allocation without hidden scratch

- `strings.clone` and `strings.join` retain their concrete arena interfaces.
  `join` restores its mark on failure.
- `strings.clone_alloc` and `strings.join_alloc` accept caller-selected output.
  Their result retains string errors plus an allocation category when relevant.
  `join_alloc` validates size before allocation. Detected overlap writes nothing
  but consumes the allocated capacity: a generic handle cannot rewind.
- `ini.parse(output, source)` validates the whole document, then allocates one
  exact-size entry table and scans again. Syntax failure consumes no output;
  allocation failure is reported separately. Entry text still borrows source.
  The scanner remains allocation-free, and no parser panic wrapper is needed.
- JSON parsing stays arena-based because its partial tree and decoded strings use
  rewind. Converting it mechanically to a generic handle would weaken rollback.

Empty generic allocations still require an initialized handle, but never call its
callback. An empty string clone or empty INI table therefore needs no capacity.
Concrete fixed/growing callbacks return uninitialized bytes; default builtins
zero payloads once. Uninitialized allocation does not promise nonzero bytes.

```dyn
use "std/mem"
use "std/strings"
use "std/encoding/ini"

fn main() {
  backing: [4 * mem.KiB]u8
  arena := mem.arena_from_buffer(backing[..])
  output := mem.arena_allocator(&arena)
  parsed := ini.parse(output, "[ui]\nname=Workbench\n")
  if !parsed.ok { #panic("invalid configuration or insufficient output capacity") }
  // Table borrows arena; text borrows the literal. Copy text when its input
  // lifetime is shorter than the desired output lifetime.
  copied := strings.clone_alloc(output, parsed.entries[1].value)
  if !copied.ok { #panic("name allocation failed") }
  // Panic form is a deliberate application policy, visible at the call site.
  counter := #alloc_or_panic(usize, output)
  counter.* = #len(copied.value)
}
```

## Cleanup and reuse audit

| Operation | Failure contract |
| --- | --- |
| Fixed arena release | Retains descriptor/backing on OS failure; retry on the same owner |
| Growing release | Earlier successful releases stay effective; remaining chain stays owned |
| Growing trim | Frees only empty blocks; partial failure retains the unreleased chain and accurate accounting |
| Linux owned-stack spawn | Spawn failure attempts release; failed release retains stack and rejects another spawn |
| Linux join | Wait/release failure retains owner; successful retry ends cleanup |
| Windows join | Wait/handle-close failure retains native handle; successful close clears it |
| macOS join | Failed native join retains handle and context; success clears them |

Do not discard a descriptor after failed cleanup. A defer that ignores a failed
release is not proof that cleanup happened. Join workers before reclaiming their
contexts/stacks. A failed spawn with no worker can still own backing requiring a
join/cleanup retry. Existing Linux error paths needed documentation and tests,
not a generalized resource framework.

`tests/std-memory-contracts.py` tests consumers, capacity/layout failures, pool
reuse, retained bytes versus zeroed bytes, partial release/trim failures, and
spawn-plus-cleanup failure followed by join retry in debug and release. Cleanup
faults are injected into temporary copies of the real std code at the OS boundary;
production APIs gain no test hooks. Successful native threading is covered by
existing host tests. Windows/macOS cleanup paths were inspected; they were not
natively fault-injected or executed here.

The changed grammar is pinned in `grammar.lock.json`; merge its upstream PR
first. Native platform gates remain release work. Further std adoption should follow concrete callers; no blanket conversion
of all arena parameters, error shapes, or cleanup APIs is planned.

## Local verification

[memory-readiness.json](validation/memory-readiness.json) records 34 passing
focused checks and the compiler fingerprint. The local build report additionally
records std source fingerprints. Coverage includes 11 complete documentation
programs and all six viability applications in debug/release, allocator target
object builds, compiler/LSP/grammar regressions, vendor bindings, native host
threading, pool reuse, and injected cleanup failures. Field-notes also builds and
runs in both modes; browser-video passes its browser target semantic check.

The repository-wide project sweep still stops at unrelated pre-existing
`projects/archive-example/main.dyn` calls to the removed `terminal.stdout`.
This is not a claim that every example or the full release gate passes.
