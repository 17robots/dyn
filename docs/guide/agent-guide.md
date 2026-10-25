# Writing Dyn applications with an agent

Read [idiomatic Dyn](idiomatic-dyn.md) first. Exact rules live in
[language](language.md), [memory](memory.md), and [buffer contracts](buffer-contracts.md).
Use real declarations and executable examples rather than borrowing syntax or APIs
from C, Go, Rust or Zig.

## Look up, write, check, run

```sh
dyn docs std/strings --json > build/strings-declarations.json
dyn check app --diagnostics json
dyn build app --output build/app
./build/app
```

`dyn docs` takes a module directory. `std/...` and `vendor/...` resolve inside
the SDK, so the same command works from any directory. It needs no language
server and no entry point.

Query an exported symbol with Python (no extra dependencies):

```sh
python3 - <<'PY'
import json
from pathlib import Path
report = json.loads(Path('build/strings-declarations.json').read_text())
for source in report['files']:
    for declaration in source['declarations']:
        if declaration['name'] == 'split':
            print(json.dumps({'path': source['path'], **declaration}, indent=2))
PY
```

Export is a live, compiler-parsed declaration index, **not** a semantic program
database. Schema 1 contains source paths, one-based line/column, kind, name,
declaration text, adjacent source comments, and parsed target directives. Function
bodies and private declarations are omitted. Comments describe author contracts;
they are not compiler-verified promises. `analysis=syntax-only` and
`target_selection=all-source-files` mean target-specific declarations are included
without proving their availability or resolving imports, types, callers, effects,
or lifetimes. Use `check --target ...` on the consuming application for validation.

The additive `contracts` object extracts one-line `Ownership:`, `Invalidation:`,
`Allocation:`, `Failure:`, and `Thread safety:` summaries from adjacent comments.
Keys are `ownership`, `invalidation`, `allocation`, `failure`, and `thread_safety`.
Missing summaries mean unspecified, not safe. Existing `source_comments` remains
the complete prose contract. These fields are not compiler-verified effects.

The non-cryptographic `source_fingerprint` covers loaded source paths and contents;
it is a local freshness hint, not a stable ID, security digest, or dependency hash.
Regenerate after changes, and record `dyn version` alongside saved indexes. Do not
accept a nonzero command exit status as a usable index. Parse errors produce no
partial index on stdout. JSON source comments retain their `//` prefixes.

## Decide storage before writing code

For every returned pointer/slice or retained callback context, answer:

1. Which storage contains it: input, caller output, arena, stack, or provider?
2. What event expires it: return, mutation, next read, rewind, reset, release?
3. Do all consumers finish before that event, including asynchronous work?
4. What happens on caller-buffer capacity or provider failure?

Prefer bounded caller output slices when practical. Use separate output/scratch
arenas for retained results and temporary work, with disjoint backing. Copy the
retained result before scratch ends. Copying a slice descriptor does not copy data.
Ordinary arena pushes return memory or panic; use `arena_try_push` when your own
code must report exhaustion. Create a `*mem.Arena` explicitly:
`mem.arena_create(0)` selects the target's default block size, while
`mem.arena_create_bounded(block_size, limit)` caps total backing, headers included.
Owned arenas add blocks without moving earlier allocations. Reset releases later
blocks and clears the first; rewind releases blocks added after its mark.

A caller-buffer arena never grows. Its header consumes `mem.ArenaHeader` bytes
plus up to 15 alignment bytes; reserve payload size plus `mem.ArenaBufferOverhead`
to guarantee payload capacity. A buffer too small for the aligned header panics.
Subarena capacity includes its header too. See [memory](memory.md) for exact limits.

A nil arena pointer is inactive, not a lazy allocator. A struct may keep a nil
owner until explicitly initialized. Pass arena pointers directly; do not construct
or copy a live header with `arena.*`. Pointer handles do not enforce uncopiability.
Release an owned arena once, then discard or nil its pointer: both it and its
allocations are invalid. Releasing nil is safe; releasing a stale owned pointer
again is not. Do not independently mutate copied owning resource descriptors.

An arena parameter does not imply deep copying: `strings.split` allocates its table
in the arena but borrows input bytes for every element. JSON `parse` allocates nodes
and decoded strings but number text borrows input. Inspect the exact source contract.
Register native resource cleanup after arena cleanup so LIFO `defer` releases the
native resource first. An arena reset does not close files or join threads.

## Choose the guarantee you need

| Mechanism | Enforced or observed | Not established |
| --- | --- | --- |
| Compiler escape diagnostic | Direct escapes, straight-line aliases and proven reset misuse | Complete lifetime proof |
| Bounds/nil/alignment checks | Those checked access conditions | Allocation still alive |
| Slot-map handle lookup | Index and live generation in the supplied slot array | Backing identity, forgery resistance or validity of retained raw views |
| Explicit value copy | Independent storage for copied scalar or fixed-array fields | Deep copying of pointer/slice fields |
| Arena poison | Diagnostic overwrite on rewind/reset | Reliable stale-access trap |
| Arena snapshot | Current counters and arena peaks/failures as pointer-free values | Synchronization or whole-program tracing |
| `std/profile` | Bounded timing events and overflow count | Unlimited retention or owned event-name strings |

Use handles when objects die independently. Keep generation backing alive, initialize
it to zero once, and preserve it on reinitialization. Never serialize handles or
reuse cleared backing while stale handles exist. Reacquire borrowed slot views at
the point of use; copy retained values into disjoint caller storage. Copy pointer
and slice payloads separately when their backing must outlive the original.

Represent meaningful alternatives with enums when that removes contradictory fields.
Missing resources and validation failures remain normal program states. Do not add
an abstraction merely to label a state; choose behavior callers can use consistently.

## Validate behavior, not just compilation

The tested programs in [memory patterns](memory-patterns.md) show lifetimes,
scratch reuse, typed pushes and snapshots. For new application code, test the actual result, exhausted capacity, cleanup on
failure, and retained output after scratch reuse. Report separately what compiled,
what ran, and what remains unverified. An AI success-rate claim needs an available
task corpus, compiler version, and reproducible results; example compilation alone
is not a general reliability score.

Semantic project queries, bounded events and sandbox execution are documented in
[tools](tools.md). They complement declaration exports.

The compiler's lifetime diagnostics are deliberately narrow; do not assume
wrapper calls or arbitrary callbacks are tracked.
