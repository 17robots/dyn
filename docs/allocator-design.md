# Primitive allocator design (removed)

Preview 16 to 18 had an `Allocator` primitive with known-callback construction
(`#allocator`), typed allocation builtins (`#alloc`, `#alloc_slice` and their
`_or_panic`/`_uninit` forms), `#AllocResult` and `AllocError`.

Preview 19 removes all of them. Allocation goes through arenas only, using the
generic `std/mem` helpers `push`, `push_array` and `push_bytes_uninit`. See the
[preview 19 migration guide](migrations/0.1.0-preview.19.md) and
[arena-first memory APIs](memory-api-direction.md).
