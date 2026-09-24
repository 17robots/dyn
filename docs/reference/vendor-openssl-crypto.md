# vendor/openssl/crypto

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/vendor/openssl/crypto/crypto.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/vendor/openssl/crypto/crypto.dyn#L4)

```dyn
pub const CipherAes256Gcm: u8 = 1
```

[Source](../../compiler/vendor/openssl/crypto/crypto.dyn#L5)

```dyn
pub const CipherChacha20Poly1305: u8 = 2
```

[Source](../../compiler/vendor/openssl/crypto/crypto.dyn#L6)

```dyn
pub struct AeadResult { written: usize, provider_code: u64, ok: bool }
```

[Source](../../compiler/vendor/openssl/crypto/crypto.dyn#L20)

Seals into ciphertext and separate 16-byte tag. All buffers caller-owned.

```dyn
pub fn aead_seal(kind: u8, ciphertext: []u8, tag: []u8, plaintext: []const u8, additional: []const u8, key: []const u8, nonce: []const u8) AeadResult
```

[Source](../../compiler/vendor/openssl/crypto/crypto.dyn#L44)

Authentication failure returns ok=false and callers must discard destination.

```dyn
pub fn aead_open(kind: u8, plaintext: []u8, ciphertext: []const u8, tag: []const u8, additional: []const u8, key: []const u8, nonce: []const u8) AeadResult
```

[Source](../../compiler/vendor/openssl/crypto/crypto.dyn#L69)

```dyn
pub struct KeyResult { written: usize, provider_code: u64, ok: bool }
```

[Source](../../compiler/vendor/openssl/crypto/crypto.dyn#L71)

```dyn
pub fn x25519_public(destination: []u8, private_key: []const u8) KeyResult
```

[Source](../../compiler/vendor/openssl/crypto/crypto.dyn#L83)

```dyn
pub fn x25519_shared(destination: []u8, private_key: []const u8, peer_public_key: []const u8) KeyResult
```

[Source](../../compiler/vendor/openssl/crypto/crypto.dyn#L100)

```dyn
pub fn ed25519_public(destination: []u8, private_key: []const u8) KeyResult
```

[Source](../../compiler/vendor/openssl/crypto/crypto.dyn#L112)

```dyn
pub fn ed25519_sign(destination: []u8, message: []const u8, private_key: []const u8) KeyResult
```

[Source](../../compiler/vendor/openssl/crypto/crypto.dyn#L126)

```dyn
pub fn ed25519_verify(signature: []const u8, message: []const u8, public_key: []const u8) bool
```

## Source: compiler/vendor/openssl/crypto/raw_generated.dyn
