# Contributing

## Quick Start

1. Install stable Rust.
2. Run formatter and tests before opening a PR:

```bash
cargo fmt
cargo test
```

## Project Conventions

- Keep large compiler modules split by domain using short snake_case chunk names.
  - Example: `expr`, `errors`, `runtime`, `builtins`, `diagnostics`.
  - Avoid long connector-heavy chunk names (like `*_and_*`).
- Keep dispatcher files as wiring only; add logic to the nearest chunk file.
  - Examples: `src/compiler/sema/typeck/infer.rs`, `src/compiler/mir/lower/function_lowerer.rs`.
- Keep tests in dedicated test modules:
  - `tests.rs` and `tests/*.rs` for themed test groups.

## Where New Code Should Go

- Parser changes: `src/compiler/parser/mod.rs` and parser tests.
- Type checking/inference changes: `src/compiler/sema/typeck/infer/*.rs`.
- MIR lowering changes: `src/compiler/mir/lower/function_lowerer/*.rs`.
- Backend/codegen changes: `src/compiler/backend/cranelift/*.rs`.
- Runtime intrinsics: `src/compiler/backend/runtime_support/*.rs`.
- Stdlib behavior changes: `std/*.dyn` with matching pipeline tests.

## Useful Scripts

- Source LOC report:

```bash
./scripts/loc.sh
```

- Local pipeline benchmark sweep:

```bash
./scripts/bench.sh . 5
```

## Spec Parity Tracking

- Use `docs/spec_status.md` to track implementation coverage and known deltas relative to `language_spec.md`.
- If behavior changes, update both tests and the parity document in the same PR.
