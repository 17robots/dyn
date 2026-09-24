# std/crypto/hmac

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

## Source: compiler/std/crypto/hmac/hmac.dyn

[Source](../../compiler/std/crypto/hmac/hmac.dyn#L3)

```dyn
pub fn sha256(destination: []u8, key: []const u8, message: []const u8) []u8
```
