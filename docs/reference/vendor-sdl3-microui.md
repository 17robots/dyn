# vendor/sdl3/microui

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/microui-sdl3-example/main.dyn](../../projects/microui-sdl3-example/main.dyn), [tests/vendor-extra.py](../../tests/vendor-extra.py), [tests/vendor-ui-render.c](../../tests/vendor-ui-render.c)

## Declarations and source contracts

## Source: compiler/vendor/sdl3/microui/microui.dyn

[Source](../../compiler/vendor/sdl3/microui/microui.dyn#L8)

Optional SDL renderer for microui's 8x16 byte-cell metrics. Built-in SDL debug
glyphs cover ASCII; this is a basic debug UI, not shaped Unicode text.
Feed events before ui.begin. Render after ui.end, then present. Uses current
renderer viewport/scale; restores clip rectangle, blend mode and draw color.

```dyn
pub fn event(context: ui.Context, renderer: sdl3.Renderer, value: *const sdl3.Event) bool
```

[Source](../../compiler/vendor/sdl3/microui/microui.dyn#L11)

```dyn
pub extern fn render "dyn_mu_sdl_render"(context: ui.Context, renderer: sdl3.Renderer) bool
```
