# std/container/string_map

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-collections/main.dyn](../../tests/sdk-collections/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/container/string_map/string_map.dyn

[Source](../../compiler/std/container/string_map/string_map.dyn#L8)

Keys are copied; values are caller-defined integer IDs/indices. Arena must
outlive the map. Removal/growth do not reclaim storage. Do not mutate entries
directly or copy a live map and then mutate both copies. No internal locking.

```dyn
pub enum ErrorKind { None, Capacity, Overflow }
```

[Source](../../compiler/std/container/string_map/string_map.dyn#L9)

```dyn
pub struct Entry { key: []const u8, value: usize, hash: u64, state: u8 }
```

[Source](../../compiler/std/container/string_map/string_map.dyn#L10)

```dyn
pub struct Map { entries: []Entry, length: usize }
```

[Source](../../compiler/std/container/string_map/string_map.dyn#L11)

```dyn
pub struct Lookup { value: usize, found: bool }
```

[Source](../../compiler/std/container/string_map/string_map.dyn#L12)

```dyn
pub struct Item { key: []const u8, value: usize, found: bool }
```

[Source](../../compiler/std/container/string_map/string_map.dyn#L33)

```dyn
pub fn get(state: *const Map, key: []const u8) Lookup
```

[Source](../../compiler/std/container/string_map/string_map.dyn#L41)

Transactional insertion: allocation failure preserves map, keys and arena mark.
Updates of existing keys allocate nothing. Growth keeps existing key bytes stable.

```dyn
pub fn put(state: *Map, arena: *memory.Arena, key: []const u8, value: usize) ErrorKind
```

[Source](../../compiler/std/container/string_map/string_map.dyn#L75)

```dyn
pub fn remove(state: *Map, key: []const u8) bool
```

[Source](../../compiler/std/container/string_map/string_map.dyn#L85)

Begin with cursor=0. Mutation invalidates iteration; returned key bytes remain
borrowed from the arena. Iteration order is unspecified.

```dyn
pub fn next(state: *const Map, cursor: *usize) Item
```
