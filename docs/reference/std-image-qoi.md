# std/image/qoi

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-image/main.dyn](../../tests/sdk-image/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/image/qoi/qoi.dyn

[Source](../../compiler/std/image/qoi/qoi.dyn#L1)

```dyn
pub struct Info { width: u32, height: u32, channels: u8, srgb: bool, ok: bool }
```

[Source](../../compiler/std/image/qoi/qoi.dyn#L2)

```dyn
pub struct Result { info: Info, pixels: []u8, error: isize, ok: bool }
```

[Source](../../compiler/std/image/qoi/qoi.dyn#L3)

```dyn
pub struct EncodeResult { data: []u8, error: isize, ok: bool }
```

[Source](../../compiler/std/image/qoi/qoi.dyn#L13)

```dyn
pub fn inspect(source: []const u8) Info
```

[Source](../../compiler/std/image/qoi/qoi.dyn#L38)

Decodes QOI into caller-owned RGBA8 storage.

```dyn
pub fn decode(destination: []u8, source: []const u8) Result
```

[Source](../../compiler/std/image/qoi/qoi.dyn#L104)

Encodes tightly packed RGB8 or RGBA8 pixels into caller-owned storage.

```dyn
pub fn encode(destination: []u8, pixels: []const u8, width: u32, height: u32, channels: u8, srgb: bool) EncodeResult
```
