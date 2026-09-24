# vendor/sdl3/image

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/vendor-packages/abi/main.dyn](../../tests/vendor-packages/abi/main.dyn)

Reviewed behavioral fixtures: [projects/sdl3-font-example/main.dyn](../../projects/sdl3-font-example/main.dyn), [projects/sdl3-image-example/main.dyn](../../projects/sdl3-image-example/main.dyn), [tests/vendor-packages.py](../../tests/vendor-packages.py), [tests/vendor-packages/abi/main.dyn](../../tests/vendor-packages/abi/main.dyn)

## Declarations and source contracts

## Source: compiler/vendor/sdl3/image/image.dyn

[Source](../../compiler/vendor/sdl3/image/image.dyn#L5)

SDL_image 3.x. Result surface is provider-owned; use sdl3.surface_destroy_owned.

```dyn
pub fn load_owned(path: []const u8, path_buffer: []u8) sdl3.SurfaceResult
```

[Source](../../compiler/vendor/sdl3/image/image.dyn#L12)

Bytes borrowed only during synchronous decode. Decoder closes its temporary IO.

```dyn
pub fn decode_owned(bytes: []const u8) sdl3.SurfaceResult
```
