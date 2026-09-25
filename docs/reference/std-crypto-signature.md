# std/crypto/signature

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-aead/main.dyn](../../tests/sdk-aead/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/crypto/signature/signature.dyn

[Source](../../compiler/std/crypto/signature/signature.dyn#L2)

```dyn
pub type Result = provider.KeyResult
```

[Source](../../compiler/std/crypto/signature/signature.dyn#L3)

```dyn
pub fn ed25519_public(destination: []u8, private_key: []const u8) Result
```

[Source](../../compiler/std/crypto/signature/signature.dyn#L4)

```dyn
pub fn ed25519_sign(destination: []u8, message: []const u8, private_key: []const u8) Result
```

[Source](../../compiler/std/crypto/signature/signature.dyn#L5)

```dyn
pub fn ed25519_verify(signature: []const u8, message: []const u8, public_key: []const u8) bool
```
