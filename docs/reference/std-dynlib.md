# std/dynlib

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/stdlib-dynlib/main.dyn](../../tests/stdlib-dynlib/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/dynlib/dynlib.dyn

Target gate: `#target(kernel: linux)`

Target gate: `#target(kernel: linux)`

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/dynlib/dynlib.dyn#L7)

POSIX dynamic-loader adapter. Handles and symbols are borrowed native pointers.
Linking a program using this module requires libc (or libdl on older systems).

```dyn
pub type Handle = rawptr
```

[Source](../../compiler/std/dynlib/dynlib.dyn#L9)

```dyn
pub const Lazy: i32 = 1
```

[Source](../../compiler/std/dynlib/dynlib.dyn#L10)

```dyn
pub const Now: i32 = 2
```

[Source](../../compiler/std/dynlib/dynlib.dyn#L11)

```dyn
pub const Local: i32 = 0
```

[Source](../../compiler/std/dynlib/dynlib.dyn#L12)

```dyn
pub const Global: i32 = 256
```

[Source](../../compiler/std/dynlib/dynlib.dyn#L14)

```dyn
pub struct OpenResult { value: Handle, error: *const u8, ok: bool }
```

[Source](../../compiler/std/dynlib/dynlib.dyn#L15)

```dyn
pub struct SymbolResult { value: rawptr, error: *const u8, ok: bool }
```

[Source](../../compiler/std/dynlib/dynlib.dyn#L22)

```dyn
pub fn open(path: []const u8, flags: i32) OpenResult
```

[Source](../../compiler/std/dynlib/dynlib.dyn#L32)

```dyn
pub fn symbol(handle: Handle, name: []const u8) SymbolResult
```

[Source](../../compiler/std/dynlib/dynlib.dyn#L43)

```dyn
pub fn close(handle: Handle) bool
```

[Source](../../compiler/std/dynlib/dynlib.dyn#L49)

Returned bytes borrow loader-owned storage and die at next loader operation.

```dyn
pub fn last_error(maximum: usize) cabi.BytesResult
```

[Source](../../compiler/std/dynlib/dynlib.dyn#L53)

```dyn
pub fn error_bytes(error: *const u8, maximum: usize) cabi.BytesResult
```
