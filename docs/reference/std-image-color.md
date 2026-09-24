# std/image/color

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

## Source: compiler/std/image/color/color.dyn

[Source](../../compiler/std/image/color/color.dyn#L1)

```dyn
pub struct Rgba { r: u8, g: u8, b: u8, a: u8 }
```

[Source](../../compiler/std/image/color/color.dyn#L3)

```dyn
pub fn rgba(r: u8, g: u8, b: u8, a: u8) Rgba
```

[Source](../../compiler/std/image/color/color.dyn#L5)

```dyn
pub fn premultiply(value: Rgba) Rgba
```

[Source](../../compiler/std/image/color/color.dyn#L15)

```dyn
pub fn luminance(value: Rgba) u8
```
