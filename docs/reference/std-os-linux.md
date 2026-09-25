# std/os/linux

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/environment-contracts/main.dyn](../../tests/environment-contracts/main.dyn)
- [tests/environment/main.dyn](../../tests/environment/main.dyn)
- [tests/process-arguments/main.dyn](../../tests/process-arguments/main.dyn)
- [tests/sdk-system/main.dyn](../../tests/sdk-system/main.dyn)
- [tests/stdlib-app/main.dyn](../../tests/stdlib-app/main.dyn)
- [tests/stdlib-net-event/main.dyn](../../tests/stdlib-net-event/main.dyn)
- [tests/stdlib-os-expanded/main.dyn](../../tests/stdlib-os-expanded/main.dyn)
- [tests/stdlib-process/main.dyn](../../tests/stdlib-process/main.dyn)
- [tests/stdlib-runtime/main.dyn](../../tests/stdlib-runtime/main.dyn)
- [tests/stdlib-system/main.dyn](../../tests/stdlib-system/main.dyn)
- [tests/vendor-packages/abi/main.dyn](../../tests/vendor-packages/abi/main.dyn)
- [tests/vendor-packages/curl/main.dyn](../../tests/vendor-packages/curl/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/os/linux/aarch64.dyn

Target gate: `#target(arch: aarch64, kernel: linux)`

## Source: compiler/std/os/linux/linux.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/os/linux/linux.dyn#L5)

```dyn
pub struct Result { value: isize, error: isize, ok: bool }
```

[Source](../../compiler/std/os/linux/linux.dyn#L19)

Linux exposes argv as NUL-separated bytes through procfs. Returned slices live
in the caller arena. Limits are explicit and intentionally modest for tools.

```dyn
pub fn process_arguments(arena: *memory.Arena) [][]const u8
```

[Source](../../compiler/std/os/linux/linux.dyn#L53)

```dyn
pub fn process_id() isize
```

[Source](../../compiler/std/os/linux/linux.dyn#L54)

```dyn
pub fn parent_process_id() isize
```

[Source](../../compiler/std/os/linux/linux.dyn#L55)

```dyn
pub fn thread_id() isize
```

[Source](../../compiler/std/os/linux/linux.dyn#L56)

```dyn
pub fn yield_thread()
```

[Source](../../compiler/std/os/linux/linux.dyn#L58)

```dyn
pub struct PipeResult { input: isize, output: isize, error: isize, ok: bool }
```

[Source](../../compiler/std/os/linux/linux.dyn#L59)

```dyn
pub struct WaitResult { process: isize, status: i32, error: isize, ok: bool }
```

[Source](../../compiler/std/os/linux/linux.dyn#L60)

```dyn
pub struct SpawnResult { process: isize, error: isize, ok: bool }
```

[Source](../../compiler/std/os/linux/linux.dyn#L61)

```dyn
pub struct SpawnOptions { input: isize, output: isize, error: isize }
```

[Source](../../compiler/std/os/linux/linux.dyn#L64)

```dyn
pub fn pipe() PipeResult
```

[Source](../../compiler/std/os/linux/linux.dyn#L70)

```dyn
pub fn close_descriptor(descriptor: isize) Result
```

[Source](../../compiler/std/os/linux/linux.dyn#L71)

```dyn
pub fn duplicate_to(descriptor: isize, target: isize) Result
```

[Source](../../compiler/std/os/linux/linux.dyn#L77)

```dyn
pub fn send_signal(process: isize, signal: usize) Result
```

[Source](../../compiler/std/os/linux/linux.dyn#L78)

```dyn
pub fn fork_process() Result
```

[Source](../../compiler/std/os/linux/linux.dyn#L91)

```dyn
pub fn execute(arena: *memory.Arena, path: []const u8, arguments: [][]const u8) isize
```

[Source](../../compiler/std/os/linux/linux.dyn#L111)

```dyn
pub fn spawn_environment(
  arena: *memory.Arena,
  path: []const u8,
  arguments: [][]const u8,
  environment: [][]const u8,
  options: SpawnOptions,
) SpawnResult
```

[Source](../../compiler/std/os/linux/linux.dyn#L193)

```dyn
pub fn wait(process: isize, nonblocking: bool) WaitResult
```

[Source](../../compiler/std/os/linux/linux.dyn#L202)

```dyn
pub fn exited(status: i32) bool
```

[Source](../../compiler/std/os/linux/linux.dyn#L203)

```dyn
pub fn exit_status(status: i32) u8
```

[Source](../../compiler/std/os/linux/linux.dyn#L204)

```dyn
pub fn signaled(status: i32) bool
```

[Source](../../compiler/std/os/linux/linux.dyn#L205)

```dyn
pub fn termination_signal(status: i32) u8
```

[Source](../../compiler/std/os/linux/linux.dyn#L207)

```dyn
pub fn exit_process(status: u8)
```

[Source](../../compiler/std/os/linux/linux.dyn#L212)

```dyn
pub struct EnvironmentResult { value: []u8, found: bool, error: isize, ok: bool }
```

[Source](../../compiler/std/os/linux/linux.dyn#L215)

Reads the process's initial environment. Values are copied into caller storage.
Not found is successful with found=false; failure may modify unused destination bytes.

```dyn
pub fn environment_get(name: []const u8, destination: []u8) EnvironmentResult
```

[Source](../../compiler/std/os/linux/linux.dyn#L257)

```dyn
pub struct PathResult { value: []u8, error: isize, ok: bool }
```

[Source](../../compiler/std/os/linux/linux.dyn#L258)

```dyn
pub fn current_directory(destination: []u8) PathResult
```

[Source](../../compiler/std/os/linux/linux.dyn#L271)

```dyn
pub fn signal_ignore(signal: usize) Result
```

[Source](../../compiler/std/os/linux/linux.dyn#L272)

```dyn
pub fn signal_default(signal: usize) Result
```

[Source](../../compiler/std/os/linux/linux.dyn#L274)

```dyn
pub fn spawn(arena: *memory.Arena, path: []const u8, arguments: [][]const u8, options: SpawnOptions) SpawnResult
```

## Source: compiler/std/os/linux/x86_64.dyn

Target gate: `#target(arch: x86_64, kernel: linux)`
