# std/compress/zstd

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-zstd/main.dyn](../../tests/sdk-zstd/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/compress/zstd/zstd.dyn

[Source](../../compiler/std/compress/zstd/zstd.dyn#L4)

```dyn
pub type Result = provider.Result
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L5)

```dyn
pub type SizeResult = provider.SizeResult
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L6)

```dyn
pub struct BufferResult { value: []u8, provider_code: usize, ok: bool }
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L7)

```dyn
pub struct Decoder {
  source_reader: stream.Reader,
  compressed_storage: []u8,
  context: provider.StreamContext,
  used: usize,
  offset: usize,
  source_ended: bool,
  frame_ended: bool,
  saw_frame: bool,
  finished: bool,
  error: isize,
}
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L19)

```dyn
pub fn version() u32
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L20)

```dyn
pub fn compress_bound(source_size: usize) usize
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L21)

```dyn
pub fn compress_into(destination: []u8, source: []const u8, level: i32) Result
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L22)

```dyn
pub fn decompress_into(destination: []u8, source: []const u8) Result
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L23)

```dyn
pub fn compress(arena: *memory.Arena, source: []const u8, level: i32) BufferResult
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L31)

```dyn
pub fn decompress(arena: *memory.Arena, source: []const u8) BufferResult
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L41)

```dyn
pub fn frame_size(source: []const u8) SizeResult
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L42)

```dyn
pub fn error_name(code: usize, maximum: usize) []const u8
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L46)

Workspace and input storage must remain alive and disjoint from output.
window_log bounds native history to 2^window_log bytes; no hidden heap allocation.

```dyn
pub fn decoder_workspace_size(window_log: u32) usize
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L47)

```dyn
pub fn decoder(input: stream.Reader, compressed_bytes: []u8, workspace: []u8, window_log: u32) Decoder
```

[Source](../../compiler/std/compress/zstd/zstd.dyn#L83)

```dyn
pub fn decoder_reader(state: *Decoder) stream.Reader
```
