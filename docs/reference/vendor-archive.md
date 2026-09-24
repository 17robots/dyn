# vendor/archive

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/archive-example/main.dyn](../../projects/archive-example/main.dyn), [tests/vendor-packages.py](../../tests/vendor-packages.py)

## Declarations and source contracts

## Source: compiler/vendor/archive/archive.dyn

[Source](../../compiler/vendor/archive/archive.dyn#L3)

```dyn
pub type Reader = rawptr
```

[Source](../../compiler/vendor/archive/archive.dyn#L4)

```dyn
pub type Entry = rawptr
```

[Source](../../compiler/vendor/archive/archive.dyn#L5)

```dyn
pub const Ok: i32 = 0
```

[Source](../../compiler/vendor/archive/archive.dyn#L6)

```dyn
pub const End: i32 = 1
```

[Source](../../compiler/vendor/archive/archive.dyn#L7)

```dyn
pub const Warn: i32 = -20
```

[Source](../../compiler/vendor/archive/archive.dyn#L8)

```dyn
pub struct OpenResult { reader: Reader, code: i32, ok: bool }
```

[Source](../../compiler/vendor/archive/archive.dyn#L9)

```dyn
pub struct EntryResult { entry: Entry, code: i32, end: bool, ok: bool }
```

[Source](../../compiler/vendor/archive/archive.dyn#L10)

```dyn
pub struct ReadResult { count: usize, code: isize, end: bool, ok: bool }
```

[Source](../../compiler/vendor/archive/archive.dyn#L13)

Reader retains source until destroy. Decoding is streaming; entry/data access
advances the reader. No filesystem extraction or path interpretation is done.

```dyn
pub fn open_memory_owned(source: []const u8) OpenResult
```

[Source](../../compiler/vendor/archive/archive.dyn#L24)

```dyn
pub fn destroy_owned(reader: Reader) i32
```

[Source](../../compiler/vendor/archive/archive.dyn#L26)

Entry and its strings expire at next header/read mutation or reader destruction.

```dyn
pub fn next(reader: Reader) EntryResult
```

[Source](../../compiler/vendor/archive/archive.dyn#L31)

```dyn
pub fn entry_name(entry: Entry, maximum: usize) c.BytesResult
```

[Source](../../compiler/vendor/archive/archive.dyn#L35)

```dyn
pub fn entry_size(entry: Entry) i64
```

[Source](../../compiler/vendor/archive/archive.dyn#L36)

```dyn
pub fn read(reader: Reader, destination: []u8) ReadResult
```

[Source](../../compiler/vendor/archive/archive.dyn#L43)

```dyn
pub fn error_message(reader: Reader, maximum: usize) c.BytesResult
```
