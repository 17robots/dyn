# vendor/zstd

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/vendor-import/main.dyn](../../tests/vendor-import/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/vendor/zstd/raw_generated.dyn

## Source: compiler/vendor/zstd/zstd.dyn

[Source](../../compiler/vendor/zstd/zstd.dyn#L3)

```dyn
pub const ContentSizeUnknown: u64 = 18446744073709551615
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L4)

```dyn
pub const ContentSizeError: u64 = 18446744073709551614
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L5)

```dyn
pub struct Result { written: usize, provider_code: usize, ok: bool }
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L6)

```dyn
pub struct SizeResult { size: u64, known: bool, ok: bool }
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L7)

```dyn
pub fn version() u32
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L8)

```dyn
pub fn compress_bound(source_size: usize) usize
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L9)

```dyn
pub fn compress(destination: []u8, source: []const u8, level: i32) Result
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L16)

```dyn
pub fn decompress(destination: []u8, source: []const u8) Result
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L23)

```dyn
pub fn frame_size(source: []const u8) SizeResult
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L29)

```dyn
pub fn error_name(code: usize, maximum: usize) []const u8
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L47)

Static provider context borrows workspace; never allocates or frees heap memory.
Advanced zstd ABI: build and run against the same supported provider version.

```dyn
pub struct StreamContext { value: rawptr, provider_code: usize, ok: bool }
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L48)

```dyn
pub struct StreamResult { written: usize, consumed: usize, provider_code: usize, ended: bool, ok: bool }
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L49)

```dyn
pub fn stream_workspace_size(window_log: u32) usize
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L56)

```dyn
pub fn stream_context(workspace: []u8, window_log: u32) StreamContext
```

[Source](../../compiler/vendor/zstd/zstd.dyn#L68)

```dyn
pub fn stream_decode(context: *StreamContext, destination: []u8, source: []const u8) StreamResult
```
