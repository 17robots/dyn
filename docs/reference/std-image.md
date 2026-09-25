# std/image

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/lsp-public-struct/main.dyn](../../tests/lsp-public-struct/main.dyn)
- [tests/sdk-image/main.dyn](../../tests/sdk-image/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/image/image.dyn

[Source](../../compiler/std/image/image.dyn#L1)

```dyn
pub enum Format { Unknown, Gray8, GrayAlpha8, Rgb8, Rgba8 }
```

[Source](../../compiler/std/image/image.dyn#L3)

```dyn
pub struct View {
  pixels: []u8,
  width: u32,
  height: u32,
  stride: usize,
  format: Format,
}
```

[Source](../../compiler/std/image/image.dyn#L11)

```dyn
pub fn bytes_per_pixel(format: Format) usize
```

[Source](../../compiler/std/image/image.dyn#L19)

```dyn
pub fn view(pixels: []u8, width: u32, height: u32, stride: usize, format: Format) View
```

[Source](../../compiler/std/image/image.dyn#L26)

```dyn
pub fn row(source: *View, y: u32) []u8
```
