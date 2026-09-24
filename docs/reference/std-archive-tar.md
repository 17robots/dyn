# std/archive/tar

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-archive/main.dyn](../../tests/sdk-archive/main.dyn)
- [tests/sdk-depth/main.dyn](../../tests/sdk-depth/main.dyn)
- [tests/sdk-lifetimes/main.dyn](../../tests/sdk-lifetimes/main.dyn)
- [tests/sdk-storage-contracts/main.dyn](../../tests/sdk-storage-contracts/main.dyn)
- [tests/stdlib-foundation/main.dyn](../../tests/stdlib-foundation/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/archive/tar/pax.dyn

[Source](../../compiler/std/archive/tar/pax.dyn#L4)

```dyn
pub struct ArchiveReader { source: []const u8, offset: usize, defaults: Overrides }
```

[Source](../../compiler/std/archive/tar/pax.dyn#L5)

```dyn
pub fn reader(source: []const u8) ArchiveReader
```

[Source](../../compiler/std/archive/tar/pax.dyn#L55)

Names and payload borrow source. Metadata records are consumed internally.
A failed call leaves both offset and persistent PAX defaults unchanged.

```dyn
pub fn next(state: *ArchiveReader) Result
```

## Source: compiler/std/archive/tar/tar.dyn

[Source](../../compiler/std/archive/tar/tar.dyn#L3)

```dyn
pub struct Entry {
  name: []const u8,
  prefix: []const u8,
  link_name: []const u8,
  size: u64,
  kind: u8,
  data: []const u8,
}
```

[Source](../../compiler/std/archive/tar/tar.dyn#L12)

```dyn
pub struct StreamReader {
  source_reader: stream.Reader,
  metadata: []u8,
  spare: []u8,
  metadata_used: usize,
  defaults: Overrides,
  header_storage: []u8,
  remaining: usize,
  padding: usize,
  active: bool,
  ended: bool,
  error: isize,
}
```

[Source](../../compiler/std/archive/tar/tar.dyn#L26)

```dyn
pub struct StreamEntry {
  name: []const u8,
  prefix: []const u8,
  link_name: []const u8,
  size: u64,
  kind: u8,
  error: isize,
  ok: bool,
}
```

[Source](../../compiler/std/archive/tar/tar.dyn#L36)

```dyn
pub fn stream_reader(input: stream.Reader, header_storage: []u8, metadata: []u8) StreamReader
```

[Source](../../compiler/std/archive/tar/tar.dyn#L98)

Input, header, and metadata storage must be disjoint. All returned names borrow
header/metadata storage until next_stream. Each metadata half must fit live
names plus the next extension payload. Empty metadata accepts plain TAR only.

```dyn
pub fn next_stream(state: *StreamReader) StreamEntry
```

[Source](../../compiler/std/archive/tar/tar.dyn#L149)

Reads entry payload incrementally. End means this entry is complete, not archive EOF.

```dyn
pub fn read_stream(state: *StreamReader, destination: []u8) stream.Result
```

[Source](../../compiler/std/archive/tar/tar.dyn#L185)

Slices borrow archive. End and Error leave offset unchanged, so both repeat.

```dyn
pub enum Status { Entry, End, Error }
```

[Source](../../compiler/std/archive/tar/tar.dyn#L186)

```dyn
pub enum ErrorKind { None, InvalidOffset, Truncated, Header }
```

[Source](../../compiler/std/archive/tar/tar.dyn#L187)

```dyn
pub struct Result { entry: Entry, status: Status, error: ErrorKind }
```
