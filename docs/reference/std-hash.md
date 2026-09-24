# std/hash

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-foundation/main.dyn](../../tests/sdk-foundation/main.dyn)
- [tests/sdk-storage-contracts/main.dyn](../../tests/sdk-storage-contracts/main.dyn)
- [tests/stdlib-data/main.dyn](../../tests/stdlib-data/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/hash/hash.dyn

[Source](../../compiler/std/hash/hash.dyn#L4)

Bounded FNV-style hash. Prime modulus avoids checked-overflow dependence.

```dyn
pub fn hash64(source: []const u8) u64
```

[Source](../../compiler/std/hash/hash.dyn#L10)

```dyn
pub fn crc32(source: []const u8) u32
```

[Source](../../compiler/std/hash/hash.dyn#L24)

```dyn
pub fn checksum32(source: []const u8) u32
```
