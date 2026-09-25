# vendor/microui

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/microui-example/main.dyn](../../projects/microui-example/main.dyn), [tests/vendor-extra.py](../../tests/vendor-extra.py)

## Declarations and source contracts

## Source: compiler/vendor/microui/microui.dyn

[Source](../../compiler/vendor/microui/microui.dyn#L7)

Fixed-capacity UI state lives entirely in caller arena. No provider heap.
Keep arena alive; reset only when finished. Single-threaded. Initial text
metrics are 8x16 monospace bytes; renderer must match (not Unicode shaping).

```dyn
pub type Context = rawptr
```

[Source](../../compiler/vendor/microui/microui.dyn#L8)

```dyn
pub type Command = rawptr
```

[Source](../../compiler/vendor/microui/microui.dyn#L9)

```dyn
pub const Clip: i32 = 2
```

[Source](../../compiler/vendor/microui/microui.dyn#L10)

```dyn
pub const Rect: i32 = 3
```

[Source](../../compiler/vendor/microui/microui.dyn#L11)

```dyn
pub const Text: i32 = 4
```

[Source](../../compiler/vendor/microui/microui.dyn#L12)

```dyn
pub const Icon: i32 = 5
```

[Source](../../compiler/vendor/microui/microui.dyn#L13)

```dyn
pub struct Rectangle { x: i32, y: i32, width: i32, height: i32 }
```

[Source](../../compiler/vendor/microui/microui.dyn#L14)

```dyn
pub fn create(arena: *mem.Arena) Context
```

[Source](../../compiler/vendor/microui/microui.dyn#L20)

```dyn
pub extern fn begin "dyn_mu_begin"(context: Context) bool
```

[Source](../../compiler/vendor/microui/microui.dyn#L21)

```dyn
pub extern fn end "dyn_mu_end"(context: Context) bool
```

[Source](../../compiler/vendor/microui/microui.dyn#L22)

```dyn
pub fn window(context: Context, title: []const u8, buffer: []u8, bounds: Rectangle) bool
```

[Source](../../compiler/vendor/microui/microui.dyn#L27)

```dyn
pub extern fn window_end "dyn_mu_window_end"(context: Context) bool
```

[Source](../../compiler/vendor/microui/microui.dyn#L28)

```dyn
pub fn label(context: Context, text: []const u8, buffer: []u8) bool
```

[Source](../../compiler/vendor/microui/microui.dyn#L33)

-1 invalid/full, 0 idle, 1 clicked. Inputs must arrive before begin().

```dyn
pub fn button(context: Context, text: []const u8, buffer: []u8) i32
```

[Source](../../compiler/vendor/microui/microui.dyn#L39)

action 0 move, 1 left press, 2 left release.

```dyn
pub extern fn mouse "dyn_mu_mouse"(context: Context, x: i32, y: i32, action: i32)
```

[Source](../../compiler/vendor/microui/microui.dyn#L42)

Iterate after end(). Commands/text borrow context storage until next begin().
Renderer handles clipping, rectangles, text and icons using the accessors.

```dyn
pub extern fn next "dyn_mu_next"(context: Context) Command
```

[Source](../../compiler/vendor/microui/microui.dyn#L43)

```dyn
pub extern fn kind "dyn_mu_kind"(command: Command) i32
```

[Source](../../compiler/vendor/microui/microui.dyn#L44)

```dyn
pub fn text(command: Command) []const u8
```

[Source](../../compiler/vendor/microui/microui.dyn#L48)

```dyn
pub fn rectangle(command: Command) Rectangle
```

[Source](../../compiler/vendor/microui/microui.dyn#L52)

RGBA packed with red in bits 31..24; independent of host byte order.

```dyn
pub extern fn color "dyn_mu_color"(command: Command) u32
```

[Source](../../compiler/vendor/microui/microui.dyn#L53)

```dyn
pub extern fn icon "dyn_mu_icon"(command: Command) i32
```
