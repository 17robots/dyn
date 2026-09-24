# std/process

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/process-platform/main.dyn](../../tests/process-platform/main.dyn)
- [tests/sdk-process/main.dyn](../../tests/sdk-process/main.dyn)
- [tests/sdk-storage-contracts/main.dyn](../../tests/sdk-storage-contracts/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/process/linux.dyn

Target gate: `#target(kernel: linux)`

## Source: compiler/std/process/macos.dyn

Target gate: `#target(kernel: darwin)`

## Source: compiler/std/process/process.dyn

[Source](../../compiler/std/process/process.dyn#L7)

Handles are native descriptors/HANDLE values. -1 inherits that standard stream.
Arguments include argv[0]. Environment is explicit NAME=value entries; empty
means an empty child environment. No shell parsing or PATH search is performed.

```dyn
pub struct Options { input: isize, output: isize, error: isize, environment: [][]const u8 }
```

[Source](../../compiler/std/process/process.dyn#L8)

```dyn
pub fn options() Options
```

[Source](../../compiler/std/process/process.dyn#L9)

```dyn
pub struct Child { handle: isize, active: bool }
```

[Source](../../compiler/std/process/process.dyn#L10)

```dyn
pub struct SpawnResult { child: Child, error: isize, ok: bool }
```

[Source](../../compiler/std/process/process.dyn#L11)

```dyn
pub struct ExitResult { code: u32, signal: u32, finished: bool, error: isize, ok: bool }
```

[Source](../../compiler/std/process/process.dyn#L12)

```dyn
pub struct Status { error: isize, ok: bool }
```

[Source](../../compiler/std/process/process.dyn#L13)

```dyn
pub struct Pipe { input: isize, output: isize, error: isize, ok: bool }
```

[Source](../../compiler/std/process/process.dyn#L14)

```dyn
pub struct EnvironmentResult { value: []u8, found: bool, error: isize, ok: bool }
```

[Source](../../compiler/std/process/process.dyn#L15)

```dyn
pub struct CaptureResult { output: []u8, errors: []u8, exit: ExitResult, timed_out: bool, limit_reached: bool, error: isize, ok: bool }
```

[Source](../../compiler/std/process/process.dyn#L19)

```dyn
pub fn spawn(arena: *mem.Arena, path: []const u8, arguments: [][]const u8, configuration: Options) SpawnResult
```

[Source](../../compiler/std/process/process.dyn#L34)

```dyn
pub fn wait(child: *Child, nonblocking: bool) ExitResult
```

[Source](../../compiler/std/process/process.dyn#L38)

```dyn
pub fn terminate(child: *Child) Status
```

[Source](../../compiler/std/process/process.dyn#L42)

```dyn
pub fn pipe() Pipe
```

[Source](../../compiler/std/process/process.dyn#L43)

```dyn
pub fn close_pipe(handle: isize) Status
```

[Source](../../compiler/std/process/process.dyn#L44)

```dyn
pub fn environment(name: []const u8, destination: []u8) EnvironmentResult
```

[Source](../../compiler/std/process/process.dyn#L52)

Drains both streams fairly. Overflow/timeout terminates and reaps the direct
child. Descendants are not killed. Negative timeout is infinite; all output
buffers are caller-owned. A nonzero child exit code is a successful capture.

```dyn
pub fn capture(arena: *mem.Arena, path: []const u8, arguments: [][]const u8,
  configuration: Options, output: []u8, errors: []u8, timeout_milliseconds: i64) CaptureResult
```

## Source: compiler/std/process/windows.dyn

Target gate: `#target(kernel: windows)`
