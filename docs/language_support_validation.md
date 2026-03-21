# Language Support Validation (Mar 2026)

This file captures a focused validation pass of language features against `language_spec.md`.

## Validation Method

- Reviewed `language_spec.md` against parser/type checker/MIR/backend diagnostics.
- Ran probe builds with `cargo run -- build <temp_project> --json` for edge syntax and inline behavior.
- Cross-checked existing test coverage under `src/compiler/pipeline/tests` and `src/compiler/sema/typeck/tests`.

## Confirmed Working (sample probes)

- `defer` with a single statement body (no braces) compiles and runs.
- `match` with single-expression arms compiles and runs.
- Labeled block break-with-value compiles and runs.

## Confirmed Limits / Not Yet Fully Supported

- Numeric backend bounds remain explicit:
  - integer widths supported in `1..=128` (`E5002` beyond that)
  - float widths supported up to `f128` (`E5002` beyond that)
- Native runtime/link behavior is still Linux-biased for full end-to-end executable parity.
  - `std/os/windows` now binds directly to `dynrt_*` runtime symbols for the shared OS facade surface (`io/env/fs/path`) instead of delegating through `std/os/linux`, but dedicated Windows-specific runtime coverage remains limited.

## Notes

- `for` expression grammar still requires a `:` separator before the loop body (`for cond: body`).
- `inline` now lowers more permissively: when direct inline lowering is not possible, lowering falls back to regular call/loop semantics instead of emitting inline-shape diagnostics.
