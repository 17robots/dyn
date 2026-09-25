# std/archive/zip

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-archive/main.dyn](../../tests/sdk-archive/main.dyn)
- [tests/sdk-storage-contracts/main.dyn](../../tests/sdk-storage-contracts/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/archive/zip/index.dyn

[Source](../../compiler/std/archive/zip/index.dyn#L6)

```dyn
pub struct OpenResult { reader: ArchiveReader, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/archive/zip/index.dyn#L44)

Checks directory framing and every local-header/descriptor relationship up front.
Payload CRCs are verified by extract, without allocating or decompressing here.

```dyn
pub fn open_checked(source: []const u8) OpenResult
```

## Source: compiler/std/archive/zip/zip.dyn

[Source](../../compiler/std/archive/zip/zip.dyn#L5)

```dyn
pub enum ErrorKind { None, End, Syntax, Unsupported, Capacity, Checksum, Overlap }
```

[Source](../../compiler/std/archive/zip/zip.dyn#L6)

```dyn
pub struct Entry {
  name: []const u8,
  payload: []const u8,
  method: u16,
  flags: u16,
  checksum: u32,
  compressed_size: usize,
  uncompressed_size: usize,
  directory: bool,
}
```

[Source](../../compiler/std/archive/zip/zip.dyn#L16)

```dyn
pub struct ArchiveReader { source: []const u8, offset: usize, indexed: bool, directory_start: usize, directory_end: usize, remaining: usize }
```

[Source](../../compiler/std/archive/zip/zip.dyn#L17)

```dyn
pub struct EntryResult { entry: Entry, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/archive/zip/zip.dyn#L18)

```dyn
pub struct ExtractResult { data: []u8, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/archive/zip/zip.dyn#L19)

```dyn
pub struct StreamReader {
  source_reader: stream.Reader,
  header_storage: []u8,
  name_storage: []u8,
  payload_storage: []u8,
  ended: bool,
  error: ErrorKind,
  system_error: isize,
}
```

[Source](../../compiler/std/archive/zip/zip.dyn#L29)

```dyn
pub fn stream_reader(input: stream.Reader, header_storage: []u8, name_storage: []u8,
  payload_storage: []u8) StreamReader
```

[Source](../../compiler/std/archive/zip/zip.dyn#L58)

Reads one local-file entry from a stream. Name and payload borrow caller storage.

```dyn
pub fn next_stream(state: *StreamReader) EntryResult
```

[Source](../../compiler/std/archive/zip/zip.dyn#L107)

```dyn
pub fn open(source: []const u8) ArchiveReader
```

[Source](../../compiler/std/archive/zip/zip.dyn#L109)

```dyn
pub fn next(state: *ArchiveReader) EntryResult
```

[Source](../../compiler/std/archive/zip/zip.dyn#L149)

Overlap/capacity/shape checks write nothing. Decode/checksum failures may write
destination, but expose no successful data. Source must remain immutable.

```dyn
pub fn extract(destination: []u8, archive_entry: Entry) ExtractResult
```
