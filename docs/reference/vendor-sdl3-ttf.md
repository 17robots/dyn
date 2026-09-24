# vendor/sdl3/ttf

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

## Source: compiler/vendor/sdl3/ttf/ttf.dyn

[Source](../../compiler/vendor/sdl3/ttf/ttf.dyn#L4)

```dyn
pub type Font = rawptr
```

[Source](../../compiler/vendor/sdl3/ttf/ttf.dyn#L5)

```dyn
pub struct FontResult { value: Font, ok: bool }
```

[Source](../../compiler/vendor/sdl3/ttf/ttf.dyn#L6)

```dyn
pub struct SizeResult { width: i32, height: i32, ok: bool }
```

[Source](../../compiler/vendor/sdl3/ttf/ttf.dyn#L9)

Init/quit must be balanced; destroy fonts before quit. Use each font on its
creating thread. SDL owns rendered surfaces; destroy them separately.

```dyn
pub fn init() bool
```

[Source](../../compiler/vendor/sdl3/ttf/ttf.dyn#L10)

```dyn
pub fn quit()
```

[Source](../../compiler/vendor/sdl3/ttf/ttf.dyn#L11)

```dyn
pub fn open_owned(path: []const u8, buffer: []u8, points: f32) FontResult
```

[Source](../../compiler/vendor/sdl3/ttf/ttf.dyn#L18)

```dyn
pub fn destroy_owned(font: Font)
```

[Source](../../compiler/vendor/sdl3/ttf/ttf.dyn#L21)

Empty text passed as an actual NUL string because SDL interprets length 0 as
NUL-terminated. Nonempty text uses byte length, never scans past the slice.

```dyn
pub fn measure(font: Font, text: []const u8) SizeResult
```

[Source](../../compiler/vendor/sdl3/ttf/ttf.dyn#L29)

```dyn
pub fn render_owned(font: Font, text: []const u8, color: sdl3.Color) sdl3.SurfaceResult
```
