# Self-host bootstrap contract

`selfhost` starts clean. The C compiler is the specification oracle until three
successive stages agree. The deleted prototypes are not the architecture of the
replacement.

## Contracts to keep stable during the rewrite

- Syntax is `tree-sitter-dyn/grammar.js`; semantic behavior is covered by
  `tests/run.sh`. New syntax requires grammar, compiler, highlighting, LSP, and
  regression tests together.
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
  Tree-sitter C API, LLVM C API, linker, and C ABI bindings.

## Required stage gates

1. `just selfhost-ready`: C compiler quality tests plus the new compiler's
   foundation executable.
2. Stage 1: the C compiler builds `selfhost`; it checks and builds the
   representative corpus.
3. Stage 2: Stage 1 builds the same source.
4. Stage 3: Stage 2 builds the same source.
5. `just selfhost-compare`: Stage 2 and Stage 3 produce byte-identical release
   executables for the corpus and identical observable output.
6. Both compilers pass the language suite, malformed-input suite, sanitizer
   suite where applicable, target object checks, and cache cold/warm tests.

Do not broaden the language to make the self-host easier. Missing compiler
operations should first become small standard-library or foreign-ABI functions;
builtins are reserved for semantics that cannot be expressed as ordinary code.
