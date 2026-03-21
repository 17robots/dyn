# Dyn Spec Parity Audit

Audit date: 2026-03-19
Baseline validation: `cargo test` (395 tests passing)

This document tracks language-spec coverage at a high level so we can close gaps intentionally.

Legend:
- `Done`: implemented and exercised by tests.
- `Partial`: implemented in major paths, but with known limits.
- `Planned`: specified but not fully implemented yet.

## Core Language Coverage

| Area | Status | Notes |
| --- | --- | --- |
| Module system, visibility, imports | Done | Resolver + parser + semantic module checks are in place. |
| Mutability, bindings, assignment | Done | `mut` checks and assignment constraints are enforced. |
| Numeric, pointer, optional, slice types | Done | End-to-end in parser/typeck/MIR/backend for tested widths, including nonstandard integer widths up to 64 bits (`iN`/`uN`). |
| `if` / `match` / `for` expressions | Done | Expression lowering and control checks are covered by tests. |
| Errorable flow (`!`, `.!`, `or`) | Done | Declared error-set compatibility is enforced in type checking. |
| `comp` and supported `inline` forms | Done | Unsupported shapes fail fast with diagnostics. |
| Builtins (`$sizeof`, `$alignof`, `$offsetof`, etc.) | Done | Type checking + lowering + runtime paths are tested. |
| Defer semantics | Done | Scope-exit + LIFO defer execution are covered, including error-only defer behavior on error and success paths. |

## Known Gaps / Follow-ups

- Address-taken aggregate mutation regressions are fixed in MIR lowering: address-taking no longer leaves stale aggregate-sequence constant folding active, and reads after pointer-based mutation now execute against runtime memory instead of stale folded values.
- Extern symbol lookup now resolves module-local extern declarations before global unqualified extern names, preventing cross-module extern-name collisions (for example `rt_eq` in `std/bytes` vs `std/mem`).
- MIR lowering now infers concrete result types for common bytes indexing/slicing expressions (`[]u8` index -> `u8` carrier, bytes slice -> `[]u8`) instead of defaulting these cases to `Unknown`.
- Backend float-width validation accepts types up to `f128` and rejects wider widths with explicit build diagnostics (`E5002`); `f128` lowering now routes through runtime-backed software quad-precision helpers (binary128 semantics on hosts with `libquadmath`), including explicit cleanup for conversion temporaries in arithmetic/compare lowering and tracked-pointer guards to prevent invalid dereference/release crashes.
- Backend integer-width validation accepts `iN`/`uN` widths in `1..=128` and rejects unsupported widths with explicit build diagnostics (`E5002`).
- Inline call/for forms now compile without hard shape diagnostics: when a call/range cannot be lowered as a direct inline expansion, lowering falls back to regular call/loop semantics.
- Native link/runtime pipeline is now multi-driver and configurable, but CI/runtime parity is still Linux-biased for full executable tests; non-Linux CI coverage now also includes resolver + MIR verifier + Cranelift backend unit tests to improve cross-platform regression detection.
- Parser diagnostics now include additional recovery hints for missing separators in call, array, and tuple literals; continue expanding targeted recovery coverage.
- Stdlib internals (especially fs/path/collections edge conditions) now include additional stress tests; continue expanding coverage for platform-specific edge behavior.

## Audit Workflow

When adding features or changing semantics:

1. Update this file (`Done`/`Partial`/`Planned`) and notes.
2. Add/adjust tests under the nearest themed `tests/*.rs` module.
3. Run at least:
   - `cargo fmt`
   - `cargo test`
4. If behavior diverges from `language_spec.md`, either align implementation or explicitly document the temporary delta here.
