# std/crypto/password

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

## Source: compiler/std/crypto/password/password.dyn

[Source](../../compiler/std/crypto/password/password.dyn#L4)

PBKDF2-HMAC-SHA256. scratch needs len(salt)+4 bytes.

```dyn
pub fn pbkdf2_sha256(destination: []u8, password: []const u8, salt: []const u8, iterations: u32, scratch: []u8) bool
```
