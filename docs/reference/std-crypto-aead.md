# std/crypto/aead

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

## Source: compiler/std/crypto/aead/aead.dyn

[Source](../../compiler/std/crypto/aead/aead.dyn#L3)

```dyn
pub enum Cipher { Aes256Gcm, Chacha20Poly1305 }
```

[Source](../../compiler/std/crypto/aead/aead.dyn#L4)

```dyn
pub type Result = provider.AeadResult
```

[Source](../../compiler/std/crypto/aead/aead.dyn#L9)

```dyn
pub fn seal(kind: Cipher, ciphertext: []u8, tag: []u8, plaintext: []const u8, additional: []const u8, key: []const u8, nonce: []const u8) Result
```

[Source](../../compiler/std/crypto/aead/aead.dyn#L12)

```dyn
pub fn open(kind: Cipher, plaintext: []u8, ciphertext: []const u8, tag: []const u8, additional: []const u8, key: []const u8, nonce: []const u8) Result
```
