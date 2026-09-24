# std/crypto/pem

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

## Source: compiler/std/crypto/pem/pem.dyn

[Source](../../compiler/std/crypto/pem/pem.dyn#L3)

```dyn
pub struct Result { data: []u8, label: []const u8, consumed: usize, ok: bool }
```

[Source](../../compiler/std/crypto/pem/pem.dyn#L16)

Decodes first PEM block. base64_storage is temporary caller memory.

```dyn
pub fn decode(destination: []u8, source: []const u8, base64_storage: []u8) Result
```
