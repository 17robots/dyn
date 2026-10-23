# Self-host bootstrap plan

Not started as a compiler. The parser exists in Dyn as a test
(`tests/selfhost-parser`) and matches `src/parser.c` node for node; it is the
seed of stage 0. The C compiler stays the specification oracle until three
successive stages agree.

## Status (2026-10-22)

| Start condition | State |
| --- | --- |
| Two previews without a breaking change | Not met: `Unreleased` has two breaking entries (cast syntax, `try_` memory names). The clock starts at the first release after a freeze. |
| Compiler library settled | Mostly: arenas, `mem.append`, intrusive lists, hash tables and slot handles, file reading, arguments and formatting exist. Open: `std/container/string_map` maps bytes to `usize` with unseeded FNV-1a. It is replaced by intrusive hash tables with seeded hashing during [std standardization](std-standardization.md). |
| Missing target modules reported | Met: one error names the module. |
| Parser port stable | Met so far: `tests/selfhost-parser` passes on 234 sources and 607 generated inputs. |

Gaps in the stage oracles:

- Stage 3 needs an IR dump. `--emit-ir` was removed with LLVM; add a stable
  text dump of the C compiler's IR first.
- Stage 2 compares `dyn check --diagnostics json`; that output exists.
- Stage 4 compares executables; `--emit-asm` exists for x86-64.

Decided 2026-10-22: no generic types
([generics design](generics-design.md#decided-no-generic-types)). Compiler
tables are concrete structs with intrusive links, as in the C compiler. Std is
standardized first, since that is the last large breaking change. Order of
work:

1. [Std standardization](std-standardization.md), including intrusive lists
   and seeded hash tables, nil stubs, and the math module.
2. A stable text dump of the C compiler's IR.
3. Freeze; two previews without a breaking change.
4. Stage 0.

The port follows the same rules as std: diagnostics go into an arena list, and
the checker continues past an error with poison stubs (`type_poison`,
`nil_symbol`) instead of stopping.

## When to start

A second compiler doubles the cost of every language change, so the rewrite
starts only when all of these hold:

- Two consecutive preview releases ship without a breaking syntax or semantic
  change (no entry marked breaking in `CHANGELOG.md`).
- The library a compiler needs is settled: arenas, `mem.append`, slot maps,
  a seeded string map, file reading, process arguments, and byte formatting.
  Collision-resistant string hashing is the open item.
- Using a module that does not support the target reports that, instead of
  "unknown function".
- `tests/selfhost-parser` has kept passing through those releases with no
  change beyond what the language changes forced.

Until then, keep the parser port in step with `src/parser.c`: a parser change
lands in both, and the comparison test guards the pair.

## Scope

Stage 1 targets `x86_64-linux` executables only: `check`, `build` and
`run`. The LSP, `fmt`, `docs`, `query`, Wasm and the other native targets
stay in C until the self-hosted compiler builds itself.

## Stages and their oracles

Each stage lives under `selfhost/` as its own module and is checked against
the C compiler on the repository corpus plus generated broken inputs, the way
`tests/selfhost-parser.py` checks the parser.

| Stage | Work | Oracle |
| --- | --- | --- |
| 0. Syntax | Move `tests/selfhost-parser` to `selfhost/syntax` | Preorder node dump, as today |
| 1. Modules | Import resolution, platform file selection, one namespace per module | File and declaration lists the C frontend loads |
| 2. Semantics | Name resolution, types, constant evaluation, lifetime and ownership checks | `dyn check --diagnostics json` byte-identical; `dyn query` JSON for the program index |
| 3. Lowering | The C compiler's IR, without optimization | IR dump (to add to the C compiler) |
| 4. Backend | x86-64 emission, the ELF object writer and the built-in linker | `--emit-asm` text, then executable output on the test corpus |
| 5. Bootstrap | Stage 1 = C builds `selfhost`; stage 2 = stage 1 builds it; stage 3 = stage 2 builds it | Stage 2 and stage 3 executables byte-identical |

Release optimization comes after stage 5; until then the self-hosted compiler
may emit debug-quality code.

## Contracts to keep stable during the rewrite

- Syntax is the bootstrap compiler's parser (`src/parser.c`); semantic behavior
  is covered by `tests/run.py`. New syntax requires parser, editor grammar,
  highlighting, LSP, and regression tests together.
- Integer widths, aggregate layout, calling convention, `any`, slices,
  `rawptr`, C variadics, target properties, and runtime entry points are ABI.
- Diagnostics use original file byte spans. Module rewriting and generated
  names must never leak into user locations.
- Compiler memory has named owners. Long-lived state uses process/module
  arenas; temporary passes use marked scratch arenas. Foreign handles are
  explicitly destroyed. No library call may allocate invisibly.
- Iteration and emitted declaration order are deterministic. Cache keys include
  compiler schema, target, options, source content, and imported interfaces.
- The bootstrap depends only on the shipped runtime, standard library,
  built-in object emitter, linker, and C ABI bindings.

## Required gates

1. `just selfhost-ready` builds a small expression compiler in Dyn and checks
   it against a Python oracle, proving the primitives a compiler needs.
2. `tests/selfhost-parser.py` passes.
3. Each stage above passes its oracle on the corpus before the next starts.
4. Stage 2 and stage 3 produce byte-identical release executables for the
   corpus and identical observable output.
5. Both compilers pass the language suite, malformed-input suite, sanitizer
   suite where applicable, target object checks, and cache cold/warm tests.

Do not broaden the language to make the self-host easier. Missing compiler
operations should first become small standard-library or foreign-ABI functions;
builtins are reserved for semantics that cannot be expressed as ordinary code.
