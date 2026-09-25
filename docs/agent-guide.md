# Writing Dyn applications with an agent

Read [idiomatic Dyn](idiomatic-dyn.md) first. Exact rules live in
[language](language.md), [memory](memory.md), and [buffer contracts](buffer-contracts.md).
Use real declarations and executable examples rather than borrowing syntax or APIs
from C, Go, Rust or Zig.

## Look up, write, check, run

From a combined workspace:

```sh
just all
./build/dyn docs compiler/std/strings --json > build/strings-declarations.json
./build/dyn check projects/memory-tour --diagnostics json --no-cache
./build/dyn build projects/memory-tour --output build/memory-tour --no-cache
./build/memory-tour
just test-agent-readiness
```

For an installed SDK, use `dyn` and the installed module directory, for example
`dyn docs /opt/dyn/share/dyn/strings --json`. Input is a module directory, not an
import name. `docs` does not need an LSP server or an entry point.

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
4. What happens on capacity or provider failure?

Prefer bounded caller output slices when practical. Use separate output/scratch
arenas for retained results and temporary work, with disjoint backing. Copy the
retained result before scratch ends. Copying a slice descriptor does not copy data.
Never independently allocate through copies of an arena or map descriptor.

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
| Slot-map handle lookup | Backing identity, index, live slot, generation | Forgery resistance or validity of retained raw views |
| `slot_map.copy_into` | Checked copy into caller output; missing/capacity do not write | Independent lifetime if output overlaps the source backing |
| Arena poison | Diagnostic overwrite on rewind/reset | Reliable stale-access trap |
| Arena/map snapshot | Current counters and arena peaks/failures as pointer-free values | Synchronization or whole-program tracing |
| `std/profile` | Bounded timing events and overflow count | Unlimited retention or owned event-name strings |

Use handles when objects die independently. Keep generation backing alive, initialize
it to zero once, and preserve it on reinitialization. Never serialize handles or
reuse cleared backing while stale handles exist. Reacquire borrowed slot views at
the point of use; use disjoint caller storage with `copy_into` for retained values.

Represent meaningful alternatives with enums when that removes contradictory fields.
Missing resources and validation failures remain normal program states. Do not add
an abstraction merely to label a state; choose behavior callers can use consistently.

## Validate behavior, not just compilation

[Memory tour](../projects/memory-tour/README.md) contains executable patterns for
lifetimes, slot reuse, explicit missing/capacity handling, snapshots and profiling.
The focused gate runs it and [memory contracts](../tests/sdk-memory-observation/main.dyn)
in debug and release, plus declaration-export checks. Tests cover stale/foreign
handles, saturation, reinitialization, capacity rollback, retained copies, scratch
overwrite and bounded trace overflow. They do not intentionally dereference expired
pointers or claim whole-program memory safety.

For new application code, test the actual result, exhausted capacity, cleanup on
failure, and retained output after scratch reuse. Report separately what compiled,
what ran, and what remains unverified. The [six-task AI trial](../benchmarks/ai/README.md)
measured 5/6 first-check passes and 6/6 final behavioral passes; this small sample
is not a general reliability score.

Semantic project queries, SQLite lookup, bounded events and sandbox execution are
documented in [preview tools](preview-tools.md). These complement declaration exports.
