# std/crypto/core

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

## Source: compiler/std/crypto/core/core.dyn

[Source](../../compiler/std/crypto/core/core.dyn#L67)

```dyn
pub struct Sha256 { state: [8]u32, tail: [64]u8, tail_length: usize, length: u64 }
```

[Source](../../compiler/std/crypto/core/core.dyn#L69)

```dyn
pub fn sha256_init(context: *Sha256)
```

[Source](../../compiler/std/crypto/core/core.dyn#L75)

Adds one chunk. False means the SHA-256 maximum input length was exceeded.

```dyn
pub fn sha256_update(context: *Sha256, input: []const u8) bool
```

[Source](../../compiler/std/crypto/core/core.dyn#L100)

Finishes into 32 caller-owned bytes. The context may be reinitialized and reused.

```dyn
pub fn sha256_finish(context: *Sha256, destination: []u8) []u8
```

[Source](../../compiler/std/crypto/core/core.dyn#L126)

Writes 32-byte SHA-256 digest. Empty slice means destination too small or oversized input.

```dyn
pub fn sha256(destination: []u8, input: []const u8) []u8
```

[Source](../../compiler/std/crypto/core/core.dyn#L132)

```dyn
pub fn hmac_sha256(destination: []u8, key: []const u8, message: []const u8) []u8
```

[Source](../../compiler/std/crypto/core/core.dyn#L154)

```dyn
pub fn equal_constant_time(left: []const u8, right: []const u8) bool
```

[Source](../../compiler/std/crypto/core/core.dyn#L163)

Linux getrandom. Success only when whole destination filled.

```dyn
pub fn secure_random(destination: []u8) bool
```
