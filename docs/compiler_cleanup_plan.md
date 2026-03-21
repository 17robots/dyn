# Compiler Cleanup Plan

This tracks concrete simplification work for the compiler/runtime codebase.

## Completed In This Pass

- Unified CLI optimization flag parsing into one helper (`parse_opt_level_cli_arg`) to remove duplicated parsing branches in `build`/`run` command handlers.
- Stabilized pipeline test temp directory generation by adding process+counter uniqueness (prevents rare parallel-test collisions).
- Fixed module-local extern lookup precedence in backend symbol resolution so unqualified extern names no longer collide across modules.
- Tightened MIR address-taken aggregate handling so pointer-based mutation invalidates stale aggregate constant-fold views.
- Expanded non-Linux CI test coverage to include module resolver, MIR verifier, and Cranelift backend unit tests.
- Consolidated diagnostics JSON emission into a shared indent-aware printer to remove duplicated pretty-print branches.
- Reused shared pipeline test helpers (`write_dyn_file`, `build_clean_project`, `run_exit_code`) in runtime/stdlib execution tests to reduce fixture boilerplate.
- Continued backend runtime-call helper cleanup in Cranelift lowering by introducing typed runtime-call wrappers (`i64`/`i32`/`f64`) and consolidating repeated soft-f128 release-call sequences.
- Completed test-helper migration across `runtime.rs`, `stdlib.rs`, and `execution.rs`, including status-only and output-based execution tests via shared helpers (`run_exit_code`, `run_output`, `run_output_in_dir`, `run_exit_code_with_env`).
- Further reduced Cranelift runtime-call duplication by centralizing declared-function call emission (`emit_declared_func_call`) and adding optional runtime symbol dispatch (`call_runtime_symbol_if_present`) reused by runtime helpers, direct-call lowering, and string literal bytes bridging.
- Simplified soft-f128 cast-to lowering by reusing the shared `lowered_to_soft_f128_ptr` conversion path.
- Reduced MIR expression-lowering duplication for field/index/slice paths by introducing shared passthrough-base and bytes-slice type helpers, plus a unified aggregate-slice view tracking helper for both range-index desugaring and explicit slice expressions.
- Reduced loop/match MIR lowering repetition by introducing shared helpers for inferred sequence element typing and sequence-or-index fallback access in `loops_match` lowering paths.
- Reduced Cranelift aggregate copy/store duplication by introducing shared leaf-copy/leaf-write helpers reused across stack-slot and pointer aggregate transfer paths.
- Normalized std OS facade wrappers by introducing shared runtime bindings in `std/os/runtime.dyn` and routing platform facade wrappers in `std/os/windows.dyn` and `std/os/linux.dyn` through that helper module (while keeping Linux syscall-backed `io_write`).
- Reduced `std/fs` wrapper repetition by introducing shared sentinel-to-error helpers (`require_u32`, `require_bytes`) for `read_all`/`write_all`/`mkdir_all`/`list_dir`.
- Applied the same sentinel-helper pattern to `std/env` and `std/unicode` by centralizing null-or-error handling (`value_or_null_bytes`, `require_bytes`, `require_u32`, `value_or_utf8_error`).
- Applied sentinel/error helper cleanup in allocator-backed containers: added `require_nonzero_ptr` in `std/heap` and `Vec(T).require_ptr` in `std/collections`, and simplified `Vec.reserve`/`Vec.push_bytes` error propagation.
- Normalized non-error sentinel status handling in `std/collections` by centralizing pointer-checked copy status (`copy_bytes_with_checked_ptr`) and removing duplicated queue bound/status checks in `peek_bytes`/`dequeue_bytes`.
- Finished a stdlib sentinel-wrapper sweep by deduplicating `std/fs/file` guard patterns (`require_nonnegative`, `require_zero_status`) and centralizing Linux `u32` status conversion in `std/os/linux` (`status_u32`) for syscall write wrappers.
- Added a first-pass `init` CLI command (`cargo run -- init [path] [--force]`) that scaffolds `main.dyn` in the current or target directory.
- Added `new` and `fmt` CLI commands: `new` creates/scaffolds a target directory, and `fmt` supports formatting or check-only normalization for `.dyn` files.

## High-Value Next Cleanup Targets

- **Backend runtime-call helpers**: continue consolidating repeated call/lowering patterns in Cranelift lowering.
- **Stdlib wrapper hygiene**: keep new wrappers aligned with the shared helper style to avoid reintroducing sentinel-conversion duplication.
- **MIR lowering ergonomics**: keep reducing duplicated index/field/slice lowering logic while preserving verifier guarantees.
- **Pipeline test ergonomics**: add focused helpers only where they remove repeated patterns without hiding test intent.

## Cleanup Principles

- Prefer one shared helper over copy-pasted branch blocks.
- Keep error messages and diagnostics behavior unchanged when refactoring.
- Add or update tests for each refactor that changes control flow.
- Avoid broad renames unless they reduce real maintenance cost.
