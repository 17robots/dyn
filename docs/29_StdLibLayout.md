# Std Library Layout Draft

This is the initial proposed layout for Dyn's standard library, aligned with explicit allocator-first design.

## Top-Level Structure

```text
std/
  prelude/
    core.dyn            # minimal always-useful aliases/helpers

  mem/
    allocator.dyn       # Allocator interface/type shape
    layout.dyn          # size/alignment helpers
    bytes.dyn           # copy/set/move wrappers and typed helpers

  heap/
    page_allocator.dyn  # binds to __dyn_os_alloc/free/realloc
    gpa.dyn             # debug/safety allocator (phase 2)
    arena.dyn           # arena allocator (phase 2)
    fixed_buffer.dyn    # stack-buffer-backed allocator (phase 2)

  io/
    print.dyn           # minimal hello-world printing surface
    writer.dyn          # writer abstraction (phase 2)

  debug/
    assert.dyn          # assert/unreachable/panic helpers

  collections/
    array_list.dyn      # first dynamic container

  os/
    linux/
      sys.dyn           # syscall constants/helpers (internal)
```

## Module Import Style

Examples:

```dyn
module main

Mem := use "std/mem"
Heap := use "std/heap"
Io := use "std/io"
```

This matches Dyn's existing `use "path/to/mod"` resolution model.

## Ownership Conventions

API docs should consistently specify one of:

- caller owns returned allocation
- ownership transferred to callee
- borrowed for call duration

## Rollout Plan

1. `std/mem` allocator and layout surface (docs + stubs)
2. `std/heap/page_allocator` backed by `__dyn_os_*`
3. `std/io/print` minimal output path
4. `std/collections/array_list` over allocator
5. Arena/GPA/fixed-buffer allocators

## Scope Notes

- This draft defines packaging and layering first; concrete function signatures may evolve as parser/type system surface grows.
- Keep phase-1 API intentionally small to preserve compatibility while allocator/runtime semantics settle.
