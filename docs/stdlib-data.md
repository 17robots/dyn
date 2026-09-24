# Data foundations

All storage is explicit. `mem.Arena` accepts caller memory; `arena_try_push` reports exhaustion without
panicking. `bytes.Builder` borrows a caller-provided slice and never grows or allocates
implicitly. Use `std/mem` arenas for explicit heap allocation. Typed containers live under `std/container`; `std/container/string_map` and
`std/bytes/builder` grow only through an explicitly supplied arena. See
[collections](collections.md) for capacity, rollback and view invalidation contracts.

`std/strings` provides checked integer parsing, correctly rounded decimal float
parsing, and ASCII helpers. `std/unicode/utf8` provides strict UTF-8 encode/decode/validation. `std/math` provides small integer math helpers. `std/reflect` helpers consume
portable scalar fields from compiler-provided `TypeInfo`.
