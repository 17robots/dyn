# Frontend Status

This document defines what the compiler frontend currently guarantees and what is intentionally deferred.

## Guaranteed

- Lexing, parsing, module graph build, symbol collection, resolver checks, and semantic checks run in a stable order.
- Modules are grouped by `(directory, module declaration)`.
- `use "path/to/mod"` resolves to a target directory and module name (last path segment), then includes all `.dyn` files in that directory with matching module declaration.
- Missing module targets and import cycles are diagnosed.
- Resolver checks module member access through `pub` exports and provides suggestions.
- Semantic checks currently include:
  - unknown identifiers
  - declaration/init type compatibility
  - core unary/binary operator compatibility
  - function call arity/type checks for simple function-literal bindings
  - loop legality for `break`/`continue`
  - range-based `for` loops with capture binding (`for a..b: |i| ...`)
  - basic aggregate duplicate member checks
  - immutable assignment checks
  - nested-scope shadowing checks
  - `if`/`match` capture names are scoped and type-checked within their branch/arm bodies
  - basic `match` overlap/exhaustiveness checks (wildcard placement, duplicate/simple-overlap patterns)
- Diagnostics are rendered consistently with file path, line/column, source line, and caret underline.

## Current Frontend Phase Order

1. Build module graph
2. Collect symbols/exports
3. Resolve module member accesses
4. Run semantic analysis
5. Print diagnostics (graph, scope, resolver, semantic)

## Intentionally Deferred

- Full type system semantics for optional/error-union/pointer/slice/array operations.
- Full function/control-flow dataflow analysis (definite assignment and full return-path proof).
- Full, type-driven exhaustiveness checking for `match`.
- Advanced generic/comptime semantics.

## Pipeline Contract

- `src/pipeline.zig` is the frontend entry point.
- `runFrontend(...)` returns a `FrontendResult` with:
  - raw phase errors
  - printed diagnostic counts
  - `canCodegen()`
  - `summary()` for stable phase counts.
