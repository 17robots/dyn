# std/io

[Reference index](README.md)

## Storage and lifetime

Reader/Writer retain their context pointers; caller keeps those contexts and buffers alive. Copy scratch is caller-owned and may live on the stack.

## Failure behavior

Copy results report partial progress and provider errors. Empty scratch is rejected before consuming input; copy_n stops at its bound or EOF. Read/write calls may complete partially.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/io-print/main.dyn](../../tests/io-print/main.dyn)
- [tests/memory-runtime/main.dyn](../../tests/memory-runtime/main.dyn)
- [tests/sdk-api-contracts/main.dyn](../../tests/sdk-api-contracts/main.dyn)
- [tests/sdk-archive/main.dyn](../../tests/sdk-archive/main.dyn)
- [tests/sdk-behavior-stress/main.dyn](../../tests/sdk-behavior-stress/main.dyn)
- [tests/sdk-boundaries/main.dyn](../../tests/sdk-boundaries/main.dyn)
- [tests/sdk-bufio/main.dyn](../../tests/sdk-bufio/main.dyn)
- [tests/sdk-cli/main.dyn](../../tests/sdk-cli/main.dyn)
- [tests/sdk-data/main.dyn](../../tests/sdk-data/main.dyn)
- [tests/sdk-depth/main.dyn](../../tests/sdk-depth/main.dyn)
- [tests/sdk-foundation/main.dyn](../../tests/sdk-foundation/main.dyn)
- [tests/sdk-hardening/main.dyn](../../tests/sdk-hardening/main.dyn)
- [tests/sdk-lifetimes/main.dyn](../../tests/sdk-lifetimes/main.dyn)
- [tests/sdk-storage-contracts/main.dyn](../../tests/sdk-storage-contracts/main.dyn)
- [tests/sdk-system/main.dyn](../../tests/sdk-system/main.dyn)
- [tests/sdk-template/main.dyn](../../tests/sdk-template/main.dyn)
- [tests/sdk-web/main.dyn](../../tests/sdk-web/main.dyn)
- [tests/sdk-zstd/main.dyn](../../tests/sdk-zstd/main.dyn)
- [tests/stdlib-contracts/main.dyn](../../tests/stdlib-contracts/main.dyn)
- [tests/stdlib-io/main.dyn](../../tests/stdlib-io/main.dyn)
- [tests/stdlib-runtime/main.dyn](../../tests/stdlib-runtime/main.dyn)
- [tests/terminal-print/main.dyn](../../tests/terminal-print/main.dyn)
- [tests/terminal-progress/main.dyn](../../tests/terminal-progress/main.dyn)

Reviewed behavioral fixtures: [tests/sdk-api-contracts/main.dyn](../../tests/sdk-api-contracts/main.dyn), [tests/sdk-behavior-stress/main.dyn](../../tests/sdk-behavior-stress/main.dyn), [tests/sdk-lifetimes/main.dyn](../../tests/sdk-lifetimes/main.dyn), [tests/sdk-storage-contracts/main.dyn](../../tests/sdk-storage-contracts/main.dyn)

## Declarations and source contracts

## Source: compiler/std/io/io.dyn

[Source](../../compiler/std/io/io.dyn#L5)

```dyn
pub enum Status { Complete, End, Error }
```

[Source](../../compiler/std/io/io.dyn#L7)

```dyn
pub struct Result {
  transferred: usize,
  error: isize,
  status: Status,
}
```

[Source](../../compiler/std/io/io.dyn#L13)

```dyn
pub struct Reader {
  data: rawptr,
  read: *fn(rawptr, []u8) Result,
}
```

[Source](../../compiler/std/io/io.dyn#L18)

```dyn
pub struct Writer {
  data: rawptr,
  write: *fn(rawptr, []const u8) Result,
}
```

[Source](../../compiler/std/io/io.dyn#L33)

```dyn
pub fn read(reader: Reader, destination: []u8) Result
```

[Source](../../compiler/std/io/io.dyn#L39)

```dyn
pub fn write(writer: Writer, source: []const u8) Result
```

[Source](../../compiler/std/io/io.dyn#L48)

```dyn
pub fn read_exact(reader: Reader, destination: []u8) Result
```

[Source](../../compiler/std/io/io.dyn#L69)

```dyn
pub fn write_all(writer: Writer, source: []const u8) Result
```

[Source](../../compiler/std/io/io.dyn#L127)

print_arguments is the non-variadic entry point used by forwarding wrappers.
The format language is intentionally small: {} inserts a value; {{ and }}
write literal braces. Invalid formats and argument-count mismatches write nothing.

```dyn
pub fn print_arguments(writer: Writer, template: []const u8, arguments: []const any) Result
```

[Source](../../compiler/std/io/io.dyn#L175)

```dyn
pub fn print(writer: Writer, template: []const u8, arguments: ...any) Result
```

[Source](../../compiler/std/io/io.dyn#L179)

```dyn
pub fn println_arguments(writer: Writer, template: []const u8, arguments: []const any) Result
```

[Source](../../compiler/std/io/io.dyn#L190)

```dyn
pub fn println(writer: Writer, template: []const u8, arguments: ...any) Result
```

[Source](../../compiler/std/io/io.dyn#L194)

```dyn
pub fn copy(writer: Writer, reader: Reader, scratch: []u8) Result
```

[Source](../../compiler/std/io/io.dyn#L220)

```dyn
pub fn copy_n(writer: Writer, reader: Reader, amount: usize, scratch: []u8) Result
```

[Source](../../compiler/std/io/io.dyn#L243)

```dyn
pub struct Cursor {
  data: []const u8,
  offset: usize,
}
```

[Source](../../compiler/std/io/io.dyn#L248)

```dyn
pub fn cursor(data: []const u8) Cursor
```

[Source](../../compiler/std/io/io.dyn#L267)

```dyn
pub fn cursor_reader(state: *Cursor) Reader
```

[Source](../../compiler/std/io/io.dyn#L271)

```dyn
pub struct BufferWriter {
  data: []u8,
  length: usize,
}
```

[Source](../../compiler/std/io/io.dyn#L276)

```dyn
pub fn buffer_writer(storage: []u8) BufferWriter
```

[Source](../../compiler/std/io/io.dyn#L280)

```dyn
pub fn buffer_writer_bytes(state: *const BufferWriter) []const u8
```

[Source](../../compiler/std/io/io.dyn#L284)

```dyn
pub fn buffer_writer_reset(state: *BufferWriter)
```

[Source](../../compiler/std/io/io.dyn#L302)

```dyn
pub fn buffer_writer_adapter(state: *BufferWriter) Writer
```
