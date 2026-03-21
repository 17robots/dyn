# Dyn Builtin and Runtime Intrinsic Surface

This document defines the policy for `$...` language builtins and runtime intrinsics.

Goal: keep `$...` focused on language/compiler semantics (Zig-style), not as a catch-all runtime API wrapper layer.

## Policy

- `$...` is reserved for **language builtins**.
- `std/` may use language builtins, but must not call runtime intrinsics through `$...` runtime aliases.
- Runtime intrinsics should be bound via `extern` declarations in std/runtime-facing modules (with `dynrt_*` link names where applicable).
- Std-foundation runtime builtin aliases are hidden from user code and produce diagnostics that point to the relevant `std/*` module.

This policy is enforced by tests:

- `runtime_intrinsic_builtins_are_declared_in_allowlists`
- `foundation_builtin_tiers_partition_foundation_surface`
- `language_builtins_are_unique_and_distinct_from_runtime_aliases`
- `std_surface_uses_only_language_builtins_and_no_runtime_aliases`

## Language Builtins

Declared in `LANGUAGE_BUILTINS` in `src/compiler/intrinsics.rs`:

- `$Self`
- `$alignof`, `$sizeof`, `$offsetof`, `$typeof`
- `$as`
- `$compile_error`, `$panic`, `$unreachable`

## Runtime Intrinsics

Runtime intrinsics are declared in `RUNTIME_INTRINSICS` in `src/compiler/intrinsics.rs` and exported as `dynrt_*` symbols.

Std-facing modules can import these symbols explicitly:

```dyn
rt_bytes_len := extern fn(value: []u8) usize = "dynrt_bytes_len"
```

Examples:

- `dynrt_alloc_with`, `dynrt_realloc_with`, `dynrt_free_with`
- `dynrt_mem_copy`, `dynrt_mem_move`, `dynrt_mem_set`, `dynrt_mem_eq`
- `dynrt_bytes_*`, `dynrt_fmt_*`
- `dynrt_strconv_parse_*`, `dynrt_unicode_utf8_*`
- `dynrt_io_*`, `dynrt_env_*`, `dynrt_fs_*`, `dynrt_path_*`
- `dynrt_linux_syscall*`, `dynrt_linux_errno`
- `dynrt_f128_*`

## Runtime Builtin Aliases

Runtime aliases are tracked by these constants:

- `STDLIB_FOUNDATION_STABLE_BUILTINS`
- `STDLIB_FOUNDATION_TRANSITIONAL_BUILTINS`
- `INTERNAL_RUNTIME_BUILTINS`

`STDLIB_FOUNDATION_*` aliases are intentionally hidden from user code in favor of std extern wrappers.

`INTERNAL_RUNTIME_BUILTINS` remain available for internal/runtime-focused tests and low-level compiler plumbing.
