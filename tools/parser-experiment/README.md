# Compact expression parser experiment

This is the first measured step toward a dedicated compiler parser. It is not
linked into Dyn and does not change `dyn check`, builds, diagnostics, or editors.
Tree-sitter remains the syntax specification and differential oracle.

Run from the compiler repository:

```sh
just test-parser-experiment
python3 tools/parser-experiment/check.py --samples 1000 --benchmark
CC=clang python3 tools/parser-experiment/check.py --sanitize
```

The runner needs the same Tree-sitter headers/runtime as the compiler, plus the
pinned grammar fetched by `just deps`. `CC`, `BUILD`, and `TS_DIR` are honored.
Benchmark JSON goes to `build/parser-experiment-work/benchmark.json` by default.
Both implementations reuse parser/storage across iterations, but Tree-sitter
returns and releases a fresh tree each time. Timings exclude process startup,
source I/O, and serialization. They are parser CPU time, not compiler wall time.

## Implemented slice

The handwritten Pratt parser supports names; number, bool, nil, string and
character literals; groups; all binary and prefix operators; dereference; fields;
scalar function arguments; indexing/slicing; `#wrap`; and `#len`. It skips ASCII
whitespace and comments. Source and operator locations are byte spans, including
UTF-8 inside literals. Nodes are 24 bytes and use indices into a caller-owned
array. The parser performs no semantic analysis or escape decoding.

Unsupported syntax fails explicitly: declarations, statements, types/type
arguments, aggregates, the remaining builtins and non-ASCII whitespace. There is
no recovery, production fallback, CLI switch, or claim of full-language coverage.
Keyword recognition is provisional until declaration/type contexts exist. The
recursion limit is 256 parser calls, independent of the production tree-depth
limit. A failed parse never exposes a root. The caller can reuse or release the
array after success or failure.

Tests compare normalized trees with Tree-sitter, including node/operator spans
and association. They cover every pair of binary operators, explicit lexical
edge cases, seeded generated expressions, deletions and invalid suffixes. Separate
unit tests inject every allocation failure in a growing tree, reuse trees after
failure, and exercise bounded reads and malformed UTF-8. The runner checks
sanitizer stderr so a crash cannot count as successful syntax rejection.

Context matters: `a[1...2]` is `a[1 .. .2]`, and `a.true` has an identifier field.
The differential oracle caught both while developing this slice. Future lexer
extensions must preserve contextual interpretations instead of assuming one
maximal tokenization works everywhere.

## Initial evidence

On the development Linux host, 1,000 parses of a 3,767-byte expression containing
calls, indexes and arithmetic took a median 0.047 CPU seconds in this parser and
0.285 in Tree-sitter, across five alternating samples on 2026-10-13. The compact
tree contains 1,199 nodes (28,776 occupied bytes, 49,152 bytes allocated capacity).
This roughly 6x result covers one expression workload only. It excludes imports,
AST lowering, semantics and LLVM; it is not a 6x `dyn check` improvement and does
not measure Tree-sitter's retained memory. CI checks correctness, not a speed floor.

## Next gates

1. Add type expressions, all builtins and aggregate expressions. Extract real
   expressions from std and tests for differential coverage. Resolve contextual
   tokens before committing to a standalone lexer interface.
2. Add declarations/statements and invalid-input coverage. Compare complete
   source trees, original spans and diagnostics over std, tests and DNA. Retain
   Tree-sitter for editor recovery and incremental edits.
3. Integrate at the syntax-to-AST seam only after parity. Import extraction,
   reference validation, scope indexing and module rewriting currently consume
   `TSNode` directly; replacing only final AST lowering cannot remove their trees.
   Migrate those consumers explicitly, with allocation-failure, cancellation and
   source-map proof. Do not wrap both parsers in a large generic node interface.
4. Measure cold full-project check/build time and peak memory on the existing
   scale and comparison suites. Enable the parser only when complete behavior
   passes and end-to-end measurements justify the maintenance cost.

The fast debug backend is a separate track. Its existing seam is checked
`DynIrProgram`, not syntax nodes. Start with a test-only x86-64 object emitter for
scalar functions and differential execution against LLVM, then add control flow,
calls, checked arithmetic, aggregates, debug/unwind metadata and the remaining
ABIs. Keep LLVM as the production backend until that target's full safety, ABI,
fault-injection and debugger contracts pass. No debug backend is implemented by
this experiment, and no unchecked arithmetic or target fallback is authorized by
its performance result.
