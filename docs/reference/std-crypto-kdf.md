# std/crypto/kdf

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

## Source: compiler/std/crypto/kdf/kdf.dyn

[Source](../../compiler/std/crypto/kdf/kdf.dyn#L3)

```dyn
pub fn hkdf_extract(destination: []u8, salt: []const u8, input_key_material: []const u8) []u8
```

[Source](../../compiler/std/crypto/kdf/kdf.dyn#L12)

scratch needs 32 + len(info) + 1 bytes. Maximum output is 255 SHA-256 blocks.

```dyn
pub fn hkdf_expand(destination: []u8, pseudorandom_key: []const u8, info: []const u8, scratch: []u8) bool
```

[Source](../../compiler/std/crypto/kdf/kdf.dyn#L33)

```dyn
pub fn hkdf(destination: []u8, salt: []const u8, input_key_material: []const u8, info: []const u8, scratch: []u8) bool
```
