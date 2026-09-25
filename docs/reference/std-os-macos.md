# std/os/macos

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/target-macos-platform/main.dyn](../../tests/target-macos-platform/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/os/macos/macos.dyn

Target gate: `#target(arch: aarch64, kernel: darwin, abi: aapcs)`

[Source](../../compiler/std/os/macos/macos.dyn#L5)

```dyn
pub struct IoResult { value: isize, error: isize, ok: bool }
```

[Source](../../compiler/std/os/macos/macos.dyn#L6)

```dyn
pub struct PollDescriptor { descriptor: i32, events: i16, returned: i16 }
```

[Source](../../compiler/std/os/macos/macos.dyn#L7)

```dyn
pub const has_native_threads: bool = false
```

[Source](../../compiler/std/os/macos/macos.dyn#L8)

```dyn
pub fn io_value(result: *const IoResult) isize
```

[Source](../../compiler/std/os/macos/macos.dyn#L19)

```dyn
pub fn file_open(path: []const u8, write_access: bool, create: bool) IoResult
```

[Source](../../compiler/std/os/macos/macos.dyn#L28)

```dyn
pub fn file_close(handle: isize) IoResult
```

[Source](../../compiler/std/os/macos/macos.dyn#L29)

```dyn
pub fn thread_yield()
```

[Source](../../compiler/std/os/macos/macos.dyn#L30)

```dyn
pub fn socket_open(family: i32, kind: i32, protocol: i32) IoResult
```

[Source](../../compiler/std/os/macos/macos.dyn#L31)

```dyn
pub fn socket_close(socket: usize) bool
```

[Source](../../compiler/std/os/macos/macos.dyn#L32)

```dyn
pub fn socket_connect(socket: usize, address: []const u8) bool
```

[Source](../../compiler/std/os/macos/macos.dyn#L36)

```dyn
pub fn event_poll(items: []PollDescriptor, milliseconds: i32) isize
```
