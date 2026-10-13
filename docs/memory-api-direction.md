# Arena-first memory APIs

This policy ships in SDK preview 19. Allocation goes through arenas only: there is
no allocator interface and no allocation builtin. See the
[migration guide](migrations/0.1.0-preview.19.md). Concrete owners and application
code decide lifetimes and failure policy.

## Compiler, std, and application responsibilities

| Layer | Responsibility |
| --- | --- |
| Compiler | Type parameters for typed std helpers, `#sizeof`/`#alignof`, narrow reset checks, tooling |
| Std | Fixed and explicitly growing arenas, typed pushes, mark/rewind/reset/release, scratch scopes, pools/free lists, domain-specific errors |
| Application | Lifetime grouping, capacity budgets, synchronization, cleanup order, recovery policy |
| Documentation and tests | Borrow/invalidation contracts, failure side effects, examples and fault-injected cleanup checks |

Existing direct local escape, owner-copy, and reset checks remain narrow. There is
no new wrapper tracing, ownership annotation language, borrow checker, GC, ARC,
automatic cleanup, or async framework. A successful compiler check does not prove
memory safety.

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
The fixed-by-default guidance and exact names are Dyn design
choices, not claims that he endorses this API.

## Failure policy

Getting memory from the OS does not fail in a way a program can handle.
`arena_create` reserves address space, and pages cost memory only once pushes
reach them, so reserve generously. When the OS refuses a reservation or a
commit, the process is out of address space or memory and `arena_create` or
the push panics. `arena_create`, `arena_release`, `frames_create`,
`frames_release`, `arena_sub`, `free_list_from_arena`, `pool_init`,
`growing_release` and `growing_trim` therefore return their value directly,
without `ok`.

A buffer arena or a sub-arena has a real size, and running out of it panics
too: every arena push (`arena_push`, `arena_push_uninit`, `arena_push_array`,
`mem.push`, `mem.push_array`, `mem.push_bytes_uninit`) either succeeds or stops
the program. Choosing the budget is the caller's job. Code with a strict budget
can use `arena_try_push`, the one push that reports exhaustion. Bounded growing
arenas, free lists and pools keep their fallible forms, since running out of
them is an expected outcome:

| Recoverable | Fatal |
| --- | --- |
| `arena_try_push` | `arena_push` and every other arena push |
| `growing_push` / `growing_push_uninit` | `growing_push_or_panic` |
| `free_list_alloc` / `pool_acquire` (nil when empty) | `free_list_alloc_or_panic` / `pool_acquire_or_panic` |
 Bounds checks, invalid free/double-free, invalid
rewind and violated layout preconditions still panic everywhere. Filesystem and
network operations keep their own status and native errors. Missing lookup
values and iterator end remain normal outcomes.

## Output allocation without hidden scratch

- `strings.clone`, `join`, `split`, `format` and `list_join` write into a
  caller's arena and return the bytes directly. Caller-buffer forms such as
  `clone_into` and `join_into` still report `Capacity`.
- `ini.parse(arena, source)` validates the whole document, then pushes one
  exact-size entry table and scans again. Syntax failure consumes no capacity.
  Entry text still borrows source.
  The scanner remains allocation-free, and no parser panic wrapper is needed.
- JSON parsing stays arena-based because its partial tree and decoded strings use
  rewind.

An empty string clone or empty INI table needs no capacity. `mem.push` and
`mem.push_array` zero their payload; `mem.push_bytes_uninit` does not, and
uninitialized bytes do not promise nonzero contents.

```dyn
use "std/mem"
use "std/strings"
use "std/encoding/ini"

fn main() {
  backing: [4 * mem.KiB]u8
  arena := mem.arena_from_buffer(backing[..])
  parsed := ini.parse(&arena, "[ui]\nname=Workbench\n")
  if !parsed.ok { #panic("invalid configuration") }
  // Table borrows arena; text borrows the literal. Copy text when its input
  // lifetime is shorter than the desired output lifetime.
  copied := strings.clone(&arena, parsed.entries[1].value)
  counter := mem.push(usize, &arena)
  counter.* = #len(copied)
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
