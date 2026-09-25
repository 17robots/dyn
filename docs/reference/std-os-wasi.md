# std/os/wasi

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [tests/wasi.py](../../tests/wasi.py)

## Declarations and source contracts

## Source: compiler/std/os/wasi/wasi.dyn

Target gate: `#target(kernel: wasi)`

[Source](../../compiler/std/os/wasi/wasi.dyn#L6)

```dyn
pub extern fn close "dyn_wasi_close"(fd: u32) u32
```

[Source](../../compiler/std/os/wasi/wasi.dyn#L11)

```dyn
pub extern fn clock_time "dyn_wasi_clock"(clock: u32, precision: u64, time: *u64) u32
```

[Source](../../compiler/std/os/wasi/wasi.dyn#L14)

Errors are WASI errno values; stream adapters expose their negative value.

```dyn
pub fn write(fd: u32, bytes: []const u8) io.Result
```

[Source](../../compiler/std/os/wasi/wasi.dyn#L21)

```dyn
pub fn read(fd: u32, bytes: []u8) io.Result
```

[Source](../../compiler/std/os/wasi/wasi.dyn#L29)

```dyn
pub struct OpenResult { fd: u32, error: u32, ok: bool }
```

[Source](../../compiler/std/os/wasi/wasi.dyn#L31)

Relative to a directory descriptor granted by the host. No implicit preopens.

```dyn
pub fn open_read(directory: u32, path: []const u8) OpenResult
```

[Source](../../compiler/std/os/wasi/wasi.dyn#L38)

```dyn
pub fn random(bytes: []u8) u32
```

[Source](../../compiler/std/os/wasi/wasi.dyn#L42)

```dyn
pub struct Arguments { values: [][]const u8, error: u32, ok: bool }
```

[Source](../../compiler/std/os/wasi/wasi.dyn#L44)

Both strings and slice descriptors belong to the supplied arena. Failure rewinds.

```dyn
pub fn arguments(arena: *mem.Arena) Arguments
```
