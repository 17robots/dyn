# std/crypto/certificate

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

## Source: compiler/std/crypto/certificate/certificate.dyn

[Source](../../compiler/std/crypto/certificate/certificate.dyn#L5)

Borrowed DER certificate view. TLS provider performs trust and hostname verification.

```dyn
pub struct Certificate { encoded: []const u8, tbs: []const u8, signature_algorithm: []const u8, signature_bits: []const u8 }
```

[Source](../../compiler/std/crypto/certificate/certificate.dyn#L6)

```dyn
pub struct Result { certificate: Certificate, ok: bool }
```

[Source](../../compiler/std/crypto/certificate/certificate.dyn#L8)

```dyn
pub fn parse(encoded: []const u8) Result
```

[Source](../../compiler/std/crypto/certificate/certificate.dyn#L25)

```dyn
pub fn fingerprint_sha256(destination: []u8, certificate: Certificate) []u8
```
