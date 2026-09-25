# std/bufio

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-boundaries/main.dyn](../../tests/sdk-boundaries/main.dyn)
- [tests/sdk-bufio/main.dyn](../../tests/sdk-bufio/main.dyn)
- [tests/stdlib-contracts/main.dyn](../../tests/stdlib-contracts/main.dyn)
- [tests/stdlib-io/main.dyn](../../tests/stdlib-io/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/bufio/bufio.dyn

[Source](../../compiler/std/bufio/bufio.dyn#L3)

```dyn
pub struct Writer {
  destination: io.Writer,
  storage: []u8,
  used: usize,
  error: isize,
}
```

[Source](../../compiler/std/bufio/bufio.dyn#L10)

```dyn
pub fn writer(destination: io.Writer, storage: []u8) Writer
```

[Source](../../compiler/std/bufio/bufio.dyn#L14)

```dyn
pub fn writer_buffered(state: *const Writer) usize
```

[Source](../../compiler/std/bufio/bufio.dyn#L16)

```dyn
pub fn writer_flush(state: *Writer) io.Result
```

[Source](../../compiler/std/bufio/bufio.dyn#L66)

```dyn
pub fn writer_adapter(state: *Writer) io.Writer
```

[Source](../../compiler/std/bufio/bufio.dyn#L70)

```dyn
pub struct Reader {
  source: io.Reader,
  storage: []u8,
  start: usize,
  end: usize,
  ended: bool,
  error: isize,
}
```

[Source](../../compiler/std/bufio/bufio.dyn#L79)

```dyn
pub fn reader(source: io.Reader, storage: []u8) Reader
```

[Source](../../compiler/std/bufio/bufio.dyn#L146)

```dyn
pub fn reader_adapter(state: *Reader) io.Reader
```

[Source](../../compiler/std/bufio/bufio.dyn#L152)

Delimiter is consumed but excluded from output. End may accompany a final
unterminated fragment. Capacity failure preserves unread input for the next call.

```dyn
pub fn read_until(state: *Reader, destination: []u8, delimiter: u8) io.Result
```

[Source](../../compiler/std/bufio/bufio.dyn#L170)

```dyn
pub fn read_line(state: *Reader, destination: []u8) io.Result
```
