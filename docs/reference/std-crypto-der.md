# std/crypto/der

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-crypto/main.dyn](../../tests/sdk-crypto/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/crypto/der/der.dyn

[Source](../../compiler/std/crypto/der/der.dyn#L1)

```dyn
pub struct Element { tag: u8, content: []const u8, encoded: []const u8, constructed: bool }
```

[Source](../../compiler/std/crypto/der/der.dyn#L2)

```dyn
pub struct Cursor { source: []const u8, offset: usize }
```

[Source](../../compiler/std/crypto/der/der.dyn#L3)

```dyn
pub struct Result { element: Element, error_offset: usize, ok: bool }
```

[Source](../../compiler/std/crypto/der/der.dyn#L5)

```dyn
pub fn cursor(source: []const u8) Cursor
```

[Source](../../compiler/std/crypto/der/der.dyn#L6)

```dyn
pub fn next(state: *Cursor) Result
```

[Source](../../compiler/std/crypto/der/der.dyn#L32)

```dyn
pub fn enter(element: Element) Cursor
```

[Source](../../compiler/std/crypto/der/der.dyn#L33)

```dyn
pub fn finished(state: *const Cursor) bool
```
