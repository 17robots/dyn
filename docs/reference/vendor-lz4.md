# vendor/lz4

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/lz4-example/main.dyn](../../projects/lz4-example/main.dyn), [tests/vendor-extra.py](../../tests/vendor-extra.py)

## Declarations and source contracts

## Source: compiler/vendor/lz4/lz4.dyn

[Source](../../compiler/vendor/lz4/lz4.dyn#L4)

Raw LZ4 blocks, not the framed format. Caller supplies the decompressed bound.
Buffers must not overlap. Failure may modify destination; discard its contents.

```dyn
pub struct Result { written: usize, code: i32, ok: bool }
```

[Source](../../compiler/vendor/lz4/lz4.dyn#L5)

```dyn
pub const MaxInput: usize = 2113929216
```

[Source](../../compiler/vendor/lz4/lz4.dyn#L6)

```dyn
pub fn compress_bound(size: usize) usize
```

[Source](../../compiler/vendor/lz4/lz4.dyn#L10)

```dyn
pub fn compress(destination: []u8, source: []const u8) Result
```

[Source](../../compiler/vendor/lz4/lz4.dyn#L18)

```dyn
pub fn decompress(destination: []u8, source: []const u8) Result
```
