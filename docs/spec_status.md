# Dyn Spec Parity Audit

Audit date: 2026-03-13
Baseline validation: `cargo test` (388 tests passing)

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

- Backend float-width validation accepts types up to `f128` and rejects wider widths with explicit build diagnostics (`E5002`); `f128` lowering now routes through runtime-backed software quad-precision helpers (binary128 semantics on hosts with `libquadmath`), including explicit cleanup for conversion temporaries in arithmetic/compare lowering.
- Backend integer-width validation accepts `iN`/`uN` widths in `1..=64` and rejects unsupported widths with explicit build diagnostics (`E5002`).
- Native link/runtime pipeline is now multi-driver and configurable, but CI/runtime parity is still Linux-biased for full executable tests.
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
