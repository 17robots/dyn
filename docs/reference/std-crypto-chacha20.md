# std/crypto/chacha20

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

## Source: compiler/std/crypto/chacha20/chacha20.dyn

[Source](../../compiler/std/crypto/chacha20/chacha20.dyn#L24)

```dyn
pub fn block(destination: []u8, key: []const u8, nonce: []const u8, counter: u32) bool
```

[Source](../../compiler/std/crypto/chacha20/chacha20.dyn#L44)

IETF ChaCha20. Input/output may be the same slice. Counter exhaustion fails.

```dyn
pub fn xor(destination: []u8, input: []const u8, key: []const u8, nonce: []const u8, counter: u32) bool
```
