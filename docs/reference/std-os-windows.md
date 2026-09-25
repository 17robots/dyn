# std/os/windows

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/target-windows-platform/main.dyn](../../tests/target-windows-platform/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/os/windows/windows.dyn

Target gate: `#target(arch: x86_64, kernel: windows, abi: win64)`

[Source](../../compiler/std/os/windows/windows.dyn#L5)

```dyn
pub struct IoResult { value: isize, error: isize, ok: bool }
```

[Source](../../compiler/std/os/windows/windows.dyn#L6)

```dyn
pub fn io_value(result: *const IoResult) isize
```

[Source](../../compiler/std/os/windows/windows.dyn#L21)

```dyn
pub struct Thread { handle: rawptr, id: u32 }
```

[Source](../../compiler/std/os/windows/windows.dyn#L22)

```dyn
pub struct PollDescriptor { descriptor: usize, events: i16, returned: i16 }
```

[Source](../../compiler/std/os/windows/windows.dyn#L23)

```dyn
pub const has_native_threads: bool = true
```

[Source](../../compiler/std/os/windows/windows.dyn#L31)

```dyn
pub fn file_open(path: []const u8, write_access: bool, create: bool) IoResult
```

[Source](../../compiler/std/os/windows/windows.dyn#L46)

```dyn
pub fn file_close(handle: isize) IoResult
```

[Source](../../compiler/std/os/windows/windows.dyn#L50)

```dyn
pub fn thread_spawn(thread: *Thread, stack_size: usize, entry: *fn(rawptr) isize, context: rawptr) bool
```

[Source](../../compiler/std/os/windows/windows.dyn#L56)

```dyn
pub fn thread_join(thread: *Thread) bool
```

[Source](../../compiler/std/os/windows/windows.dyn#L63)

```dyn
pub fn thread_yield()
```

[Source](../../compiler/std/os/windows/windows.dyn#L64)

```dyn
pub fn socket_open(family: i32, kind: i32, protocol: i32) IoResult
```

[Source](../../compiler/std/os/windows/windows.dyn#L69)

```dyn
pub fn socket_close(socket: usize) bool
```

[Source](../../compiler/std/os/windows/windows.dyn#L70)

```dyn
pub fn socket_connect(socket: usize, address: []const u8) bool
```

[Source](../../compiler/std/os/windows/windows.dyn#L74)

```dyn
pub fn event_poll(items: []PollDescriptor, milliseconds: i32) isize
```
