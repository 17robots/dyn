# Runtime Memory Model (Current)

This document defines the current runtime memory strategy used by IR lowering and backend execution paths.

## Storage Classes

- Local stack slots: per-function storage for locals/params.
- Module/global slots: process-lifetime mutable storage allocated per compiled unit.
- Read-only data: string constants in `.rodata`.

## Pointer Model (Current)

Pointers are represented as addresses in direct asm and as tagged pointer spaces in the interpreter path.

- `addr_of_local <slot>` points to function-local slot storage.
- `addr_of_global <slot>` points to module/global slot storage.
- `ptr_offset_slots <n>` offsets a pointer by `n` slot-elements.
- `load_ptr` / `store_ptr` dereference pointer values.

## Runtime Backing Allocator Symbols

Current runtime also provides low-level backing allocator entry points:

- `__dyn_os_alloc(size, align)`
- `__dyn_os_free(ptr, size, align)`
- `__dyn_os_realloc(ptr, old_size, old_align, new_size, new_align)`

These are intended as the base allocator layer for std allocator implementations.

Current slot element width is one machine word (`8` bytes on Linux x86_64).

## Ownership/Lifetime Policy (Current)

- Local slot lifetime: function activation frame.
- Global slot lifetime: entire process runtime.
- No automatic heap allocator is exposed in language/runtime yet.
- No borrow checker or alias-tracking ownership model is enforced yet.

## Safety/Validation (Current)

- Semantic layer enforces pointer mutability (`*T` vs `*mut T`) and element-type compatibility.
- Interpreter rejects invalid pointer space accesses.
- Direct asm assumes valid lowered IR and uses process memory semantics.

## Out of Scope (Pending)

- Heap allocation API and allocator strategy.
- Full ownership/lifetime system.
- Compound aggregate pointer semantics beyond slot-based offsets.
