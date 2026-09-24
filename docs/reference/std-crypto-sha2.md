# std/crypto/sha2

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-depth/main.dyn](../../tests/sdk-depth/main.dyn)
- [tests/stdlib-depth/main.dyn](../../tests/stdlib-depth/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/crypto/sha2/sha2.dyn

[Source](../../compiler/std/crypto/sha2/sha2.dyn#L3)

```dyn
pub type Sha256 = crypto_core.Sha256
```

[Source](../../compiler/std/crypto/sha2/sha2.dyn#L4)

```dyn
pub fn init(context: *Sha256)
```

[Source](../../compiler/std/crypto/sha2/sha2.dyn#L5)

```dyn
pub fn update(context: *Sha256, input: []const u8) bool
```

[Source](../../compiler/std/crypto/sha2/sha2.dyn#L6)

```dyn
pub fn finish(context: *Sha256, destination: []u8) []u8
```

[Source](../../compiler/std/crypto/sha2/sha2.dyn#L7)

```dyn
pub fn sum256(destination: []u8, input: []const u8) []u8
```

[Source](../../compiler/std/crypto/sha2/sha2.dyn#L8)

```dyn
pub fn equal_constant_time(left: []const u8, right: []const u8) bool
```
