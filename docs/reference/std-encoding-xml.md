# std/encoding/xml

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-data/main.dyn](../../tests/sdk-data/main.dyn)
- [tests/sdk-hardening/main.dyn](../../tests/sdk-hardening/main.dyn)
- [tests/sdk-lifetimes/main.dyn](../../tests/sdk-lifetimes/main.dyn)
- [tests/sdk-namespaces/main.dyn](../../tests/sdk-namespaces/main.dyn)
- [tests/sdk-storage-contracts/main.dyn](../../tests/sdk-storage-contracts/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/encoding/xml/namespaces.dyn

[Source](../../compiler/std/encoding/xml/namespaces.dyn#L3)

Namespace context works with buffered or streaming events. Caller storage owns
copied scope names and normalized namespace URIs; capacity failure is explicit.

```dyn
pub struct NamespaceBinding { prefix: []const u8, uri: []const u8 }
```

[Source](../../compiler/std/encoding/xml/namespaces.dyn#L4)

```dyn
pub struct NamespaceFrame { name: []const u8, bindings: usize, used: usize }
```

[Source](../../compiler/std/encoding/xml/namespaces.dyn#L5)

```dyn
pub struct Namespaces {
  bindings: []NamespaceBinding, frames: []NamespaceFrame, storage: []u8,
  count: usize, depth: usize, used: usize,
}
```

[Source](../../compiler/std/encoding/xml/namespaces.dyn#L9)

```dyn
pub struct ExpandedName { prefix: []const u8, local: []const u8, uri: []const u8, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/encoding/xml/namespaces.dyn#L12)

```dyn
pub fn namespaces(bindings: []NamespaceBinding, frames: []NamespaceFrame, storage: []u8) Namespaces
```

[Source](../../compiler/std/encoding/xml/namespaces.dyn#L26)

```dyn
pub fn namespace_resolve(state: *const Namespaces, name: []const u8, attribute: bool) ExpandedName
```

[Source](../../compiler/std/encoding/xml/namespaces.dyn#L116)

Enter every Start, including self-closing tags; leave it after consuming its
attributes. Failed enter restores scope counters; unused storage may change.
Expanded element slices last until scope exit.

```dyn
pub fn namespace_enter(state: *Namespaces, event: Event) ExpandedName
```

[Source](../../compiler/std/encoding/xml/namespaces.dyn#L123)

```dyn
pub fn namespace_leave(state: *Namespaces, name: []const u8) bool
```

## Source: compiler/std/encoding/xml/xml.dyn

[Source](../../compiler/std/encoding/xml/xml.dyn#L5)

```dyn
pub enum Kind { Start, End, Text, Comment, Processing, Cdata }
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L6)

```dyn
pub enum ErrorKind { None, Syntax, Capacity, Mismatched, Overlap }
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L7)

```dyn
pub struct Event { kind: Kind, name: []const u8, text: []const u8, attributes: []const u8, self_closing: bool }
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L8)

```dyn
pub struct Scanner { source: []const u8, offset: usize, error_offset: usize, error: ErrorKind }
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L9)

```dyn
pub struct StreamScanner { input: stream.Reader, storage: []u8, used: usize, consumed: usize, scanned: usize, quote: u8, ended: bool, system_error: isize }
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L10)

```dyn
pub struct Result { event: Event, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L11)

```dyn
pub struct AttributeScanner { source: []const u8, offset: usize, error: ErrorKind }
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L12)

```dyn
pub struct Attribute { name: []const u8, value: []const u8, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L13)

```dyn
pub struct Writer { sink: stream.Writer, error: isize, failed: bool }
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L15)

```dyn
pub fn scanner(source: []const u8) Scanner
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L16)

```dyn
pub fn stream_scanner(input: stream.Reader, storage: []u8) StreamScanner
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L28)

Events borrow storage until the next call. Text may be returned in multiple events.

```dyn
pub fn next_stream(state: *StreamScanner) Result
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L62)

```dyn
pub fn writer(destination_writer: stream.Writer) Writer
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L90)

```dyn
pub fn write_text(state: *Writer, value: []const u8) bool
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L91)

```dyn
pub fn write_start(state: *Writer, name: []const u8) bool
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L94)

```dyn
pub fn write_attribute(state: *Writer, name: []const u8, value: []const u8) bool
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L98)

```dyn
pub fn write_start_end(state: *Writer, self_closing: bool) bool
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L102)

```dyn
pub fn write_end(state: *Writer, name: []const u8) bool
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L180)

```dyn
pub fn next(state: *Scanner) Result
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L236)

```dyn
pub fn attributes(event: Event) AttributeScanner
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L241)

```dyn
pub fn next_attribute(state: *AttributeScanner) Attribute
```

[Source](../../compiler/std/encoding/xml/xml.dyn#L277)

```dyn
pub fn valid(source: []const u8, stack: [][]const u8) bool
```
