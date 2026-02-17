# Std API Shape Draft

This draft describes a minimal standard-library API surface aligned with explicit allocator usage (Zig-like ergonomics, simplified for current Dyn).

## Design Principles

- Allocator is passed explicitly.
- Container/object APIs that may allocate take allocator parameter or store allocator handle.
- Ownership transfer is documented at function boundaries.

## Core Types

## `std.mem.Allocator`

Conceptual shape:

```dyn
Allocator := struct {
    alloc: fn(*mut Allocator, usize, usize) *mut u8,
    free: fn(*mut Allocator, *mut u8, usize, usize) void,
    realloc: fn(*mut Allocator, *mut u8, usize, usize, usize, usize) *mut u8,
}
```

Notes:

- First parameter is allocator state/context receiver.
- Returns null pointer on failure in v1.
- Typed wrappers provide safer ergonomics over raw `u8` pointers.

## `std.heap`

Proposed starting allocators:

- `std.heap.page_allocator` (process-backed baseline allocator)
- `std.heap.GeneralPurposeAllocator` (safety-oriented wrapper)
- `std.heap.ArenaAllocator` (bulk free pattern)

Phase-1 requirement: only `page_allocator` equivalent is needed to bootstrap.

## Typed Helper Layer

`std.mem` helper functions (thin wrappers):

- `alloc(comptime T, allocator, n) -> *mut T` (or nullable pointer in v1 shape)
- `free(comptime T, allocator, ptr, n)`
- `realloc(comptime T, allocator, ptr, old_n, new_n) -> *mut T`

These wrappers compute `size = n * size_of(T)` and `align = align_of(T)`.

## Containers (After Allocator Base)

First container to prioritize:

- `std.ArrayList(T)`

Minimal API target:

- `init(allocator)`
- `deinit()`
- `append(value)`
- `appendSlice(items)`
- `items()` view/slice

All operations that may grow storage route through allocator.

## Ownership Documentation Convention

Adopt explicit wording in docs/APIs:

- "caller owns returned memory"
- "ownership transferred to callee"
- "borrowed for call duration"

This provides practical lifetime clarity before static ownership analysis exists.

## Suggested Rollout

1. Runtime backing allocator ABI symbols (`__dyn_os_alloc/free/realloc`).
2. `std.mem.Allocator` skeleton + page allocator binding.
3. Typed alloc/free wrappers in `std.mem`.
4. One dynamic container (`ArrayList`).
5. Expand diagnostics for leaks/mismatched frees in debug-oriented allocators.
