# vendor/stb/image_resize

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/stb-example/main.dyn](../../projects/stb-example/main.dyn), [tests/vendor-extra.py](../../tests/vendor-extra.py), [tests/vendor-stb-native.c](../../tests/vendor-stb-native.c)

## Declarations and source contracts

## Source: compiler/vendor/stb/image_resize/image_resize.dyn

[Source](../../compiler/vendor/stb/image_resize/image_resize.dyn#L7)

Tightly packed u8 pixels, 1..4 channels, dimensions 1..32768. RGBA uses
straight alpha. RGB/RGBA may use sRGB; alpha remains linear. No in-place resize.
All temporary storage comes from scratch, which is rewound before returning.
Source/destination storage must remain outside the scratch allocation range.

```dyn
pub fn resize(scratch: *mem.Arena, source: []const u8, width: i32, height: i32, destination: []u8, out_width: i32, out_height: i32, channels: i32, srgb: bool) bool
```
