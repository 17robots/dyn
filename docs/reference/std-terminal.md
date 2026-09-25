# std/terminal

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/memory-runtime/main.dyn](../../tests/memory-runtime/main.dyn)
- [tests/stdlib-io/main.dyn](../../tests/stdlib-io/main.dyn)
- [tests/stdlib-os-expanded/main.dyn](../../tests/stdlib-os-expanded/main.dyn)
- [tests/stdlib-runtime/main.dyn](../../tests/stdlib-runtime/main.dyn)
- [tests/stdlib-system/main.dyn](../../tests/stdlib-system/main.dyn)
- [tests/terminal-print/main.dyn](../../tests/terminal-print/main.dyn)
- [tests/terminal-progress/main.dyn](../../tests/terminal-progress/main.dyn)

Reviewed behavioral fixtures: [tests/wasi.py](../../tests/wasi.py)

## Declarations and source contracts

## Source: compiler/std/terminal/terminal.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/terminal/terminal.dyn#L42)

```dyn
pub fn stdin() stream.Reader
```

[Source](../../compiler/std/terminal/terminal.dyn#L43)

```dyn
pub fn stdout() stream.Writer
```

[Source](../../compiler/std/terminal/terminal.dyn#L44)

```dyn
pub fn stderr() stream.Writer
```

[Source](../../compiler/std/terminal/terminal.dyn#L46)

```dyn
pub struct State { bytes: [60]u8 }
```

[Source](../../compiler/std/terminal/terminal.dyn#L47)

```dyn
pub struct Size { columns: usize, rows: usize, ok: bool }
```

[Source](../../compiler/std/terminal/terminal.dyn#L49)

```dyn
pub fn read_state(descriptor: isize, output: *State) bool
```

[Source](../../compiler/std/terminal/terminal.dyn#L53)

```dyn
pub fn restore(descriptor: isize, saved: *const State) bool
```

[Source](../../compiler/std/terminal/terminal.dyn#L57)

```dyn
pub fn is_attached(descriptor: isize) bool
```

[Source](../../compiler/std/terminal/terminal.dyn#L63)

Applies a small cfmakeraw-equivalent while retaining a restorable copy.

```dyn
pub fn raw(descriptor: isize, previous: *State) bool
```

[Source](../../compiler/std/terminal/terminal.dyn#L77)

```dyn
pub fn size(descriptor: isize) Size
```

[Source](../../compiler/std/terminal/terminal.dyn#L85)

```dyn
pub enum KeyKind { Text, Escape, Up, Down, Left, Right, Home, End, Delete, Unknown, Incomplete }
```

[Source](../../compiler/std/terminal/terminal.dyn#L86)

```dyn
pub struct Key { kind: KeyKind, codepoint: u32, consumed: usize }
```

[Source](../../compiler/std/terminal/terminal.dyn#L89)

Recognizes UTF-8 text and common CSI cursor keys. Incomplete sequences consume
nothing. A standalone ESC is returned immediately; callers choose any timeout.

```dyn
pub fn key_decode(bytes: []const u8) Key
```

## Source: compiler/std/terminal/wasi.dyn

Target gate: `#target(kernel: wasi)`

[Source](../../compiler/std/terminal/wasi.dyn#L7)

```dyn
pub fn stdin() io.Reader
```

[Source](../../compiler/std/terminal/wasi.dyn#L8)

```dyn
pub fn stdout() io.Writer
```

[Source](../../compiler/std/terminal/wasi.dyn#L9)

```dyn
pub fn stderr() io.Writer
```
