# std/bytes/builder

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

## Source: compiler/std/bytes/builder/builder.dyn

[Source](../../compiler/std/bytes/builder/builder.dyn#L5)

Byte and UTF-8 string construction share this byte-oriented builder. No UTF-8
validation is implied. A builder borrows storage; arena growth is explicit.

```dyn
pub enum ErrorKind { None, Capacity, Overflow, InvalidState }
```

[Source](../../compiler/std/bytes/builder/builder.dyn#L6)

```dyn
pub struct Builder { storage: []u8, length: usize }
```

[Source](../../compiler/std/bytes/builder/builder.dyn#L8)

```dyn
pub fn from_buffer(storage: []u8) Builder
```

[Source](../../compiler/std/bytes/builder/builder.dyn#L9)

```dyn
pub fn bytes(state: *const Builder) []const u8
```

[Source](../../compiler/std/bytes/builder/builder.dyn#L10)

```dyn
pub fn clear(state: *Builder)
```

[Source](../../compiler/std/bytes/builder/builder.dyn#L14)

Exact capacity reservation. Failure changes neither builder nor arena.
Old arena buffers remain allocated until the caller rewinds or resets.

```dyn
pub fn reserve(state: *Builder, arena: *memory.Arena, capacity: usize) ErrorKind
```

[Source](../../compiler/std/bytes/builder/builder.dyn#L26)

Bounded append supports overlap/self-append. Failure writes nothing.

```dyn
pub fn append(state: *Builder, source: []const u8) ErrorKind
```

[Source](../../compiler/std/bytes/builder/builder.dyn#L36)

Geometric growth with exact-size fallback for a nearly exhausted arena.
Existing views must be reacquired after mutation. Source may borrow this builder.

```dyn
pub fn append_grow(state: *Builder, arena: *memory.Arena, source: []const u8) ErrorKind
```
