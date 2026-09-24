# std/encoding/csv

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-data/main.dyn](../../tests/sdk-data/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/encoding/csv/csv.dyn

[Source](../../compiler/std/encoding/csv/csv.dyn#L4)

```dyn
pub enum ErrorKind { None, Syntax, Capacity }
```

[Source](../../compiler/std/encoding/csv/csv.dyn#L5)

```dyn
pub struct Scanner { source: []const u8, offset: usize, finished: bool }
```

[Source](../../compiler/std/encoding/csv/csv.dyn#L6)

```dyn
pub struct StreamScanner { input: stream.Reader, lookahead: u8, has_lookahead: bool, pending: bool, finished: bool, error: isize }
```

[Source](../../compiler/std/encoding/csv/csv.dyn#L7)

```dyn
pub struct Field { text: []u8, end_record: bool, end_input: bool, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/encoding/csv/csv.dyn#L9)

```dyn
pub struct Writer { sink: stream.Writer, fields: usize, failed: bool, error: isize }
```

[Source](../../compiler/std/encoding/csv/csv.dyn#L11)

```dyn
pub fn scanner(source: []const u8) Scanner
```

[Source](../../compiler/std/encoding/csv/csv.dyn#L12)

```dyn
pub fn stream_scanner(input: stream.Reader) StreamScanner
```

[Source](../../compiler/std/encoding/csv/csv.dyn#L26)

Reads one field from an arbitrarily chunked input stream.

```dyn
pub fn next_stream(state: *StreamScanner, destination: []u8) Field
```

[Source](../../compiler/std/encoding/csv/csv.dyn#L69)

```dyn
pub fn writer(destination_writer: stream.Writer) Writer
```

[Source](../../compiler/std/encoding/csv/csv.dyn#L79)

Writes one field. `end_record` emits CRLF; otherwise the next field is comma-separated.

```dyn
pub fn write_field(state: *Writer, value: []const u8, end_record: bool) bool
```

[Source](../../compiler/std/encoding/csv/csv.dyn#L106)

```dyn
pub fn next(state: *Scanner, destination: []u8) Field
```
