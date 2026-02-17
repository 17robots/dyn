# Allocator ABI Draft (Zig-Style Direction)

This document defines a concrete first-pass allocator ABI for Dyn, modeled after Zig's explicit allocator-driven style.

## Goals

- Make heap allocation explicit at callsites.
- Avoid hidden global allocators in language semantics.
- Keep runtime ABI small and backend-friendly.
- Enable a minimal `std.mem.Allocator`-like API in Dyn source.

## Runtime Symbols

The compiler/runtime provides these low-level backing symbols:

- `__dyn_os_alloc(size: i64, align: i64) -> i64`
- `__dyn_os_free(ptr: i64, size: i64, align: i64) -> void`
- `__dyn_os_realloc(ptr: i64, old_size: i64, old_align: i64, new_size: i64, new_align: i64) -> i64`

Return/argument `i64` is pointer-sized in the current Linux x86_64 baseline.

## Semantics

- `size == 0`:
  - `os_alloc`: may return null (`0`) or unique non-dereferenceable token (implementation-defined).
  - `os_free`: no-op.
- `align` must be power-of-two and `>= 1`.
- On OOM, `os_alloc`/`os_realloc` return `0`.
- `os_free` accepts `0` pointer and behaves as no-op.
- `os_realloc(0, 0, _, new_size, new_align)` is equivalent to `os_alloc(new_size, new_align)`.

These symbols are not the high-level allocator interface. They are intended as the base allocator used by std allocators (for example, a page allocator wrapper).

## Ownership Contract

- Allocation ownership is explicit and API-defined.
- The caller that receives the pointer is responsible for releasing it unless ownership is transferred.
- Cross-boundary free must use the allocator/runtime family that allocated the block.

## IR Mapping

Preferred lowering strategy (phase 1): lower allocator operations to internal-callable runtime backing symbols.

- `heap_alloc(size, align)` -> call `__dyn_os_alloc`
- `heap_free(ptr, size, align)` -> call `__dyn_os_free`
- `heap_realloc(...)` -> call `__dyn_os_realloc`

Alternative strategy (phase 2): dedicated IR ops once optimizer/runtime analysis is added.

## Error Model

- Phase 1: nullable-pointer failure path (`0` means failure).
- Phase 2: optional/error integration (`.?`/`.!`) and richer typed alloc result wrappers.

## Initial Runtime Implementation

- Linux x86_64 direct-asm backend can provide default C-backed stubs (malloc/free/realloc), or emit unresolved externs to be linked by driver.
- The driver remains responsible for linking behavior and symbol resolution diagnostics.

## Non-Goals (This Phase)

- Moving GC.
- Borrow checker / affine ownership typing.
- Implicit lifetime inference across function boundaries.
