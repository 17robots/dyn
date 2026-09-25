# std/bytes

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-api-contracts/main.dyn](../../tests/sdk-api-contracts/main.dyn)
- [tests/sdk-behavior-stress/main.dyn](../../tests/sdk-behavior-stress/main.dyn)
- [tests/sdk-collections/main.dyn](../../tests/sdk-collections/main.dyn)
- [tests/sdk-foundation/main.dyn](../../tests/sdk-foundation/main.dyn)
- [tests/sdk-hardening/main.dyn](../../tests/sdk-hardening/main.dyn)
- [tests/sdk-http-workers/main.dyn](../../tests/sdk-http-workers/main.dyn)
- [tests/sdk-lifetimes/main.dyn](../../tests/sdk-lifetimes/main.dyn)
- [tests/sdk-namespaces/main.dyn](../../tests/sdk-namespaces/main.dyn)
- [tests/sdk-process/main.dyn](../../tests/sdk-process/main.dyn)
- [tests/sdk-sqlite/main.dyn](../../tests/sdk-sqlite/main.dyn)
- [tests/sdk-storage-contracts/main.dyn](../../tests/sdk-storage-contracts/main.dyn)
- [tests/sdk-unicode-text/main.dyn](../../tests/sdk-unicode-text/main.dyn)
- [tests/sdk-watch/main.dyn](../../tests/sdk-watch/main.dyn)
- [tests/stdlib-mem-extra/main.dyn](../../tests/stdlib-mem-extra/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/bytes/bytes.dyn

[Source](../../compiler/std/bytes/bytes.dyn#L3)

```dyn
pub fn equal(left: []const u8, right: []const u8) bool
```

[Source](../../compiler/std/bytes/bytes.dyn#L8)

```dyn
pub fn compare(left: []const u8, right: []const u8) i32
```

[Source](../../compiler/std/bytes/bytes.dyn#L22)

```dyn
pub fn starts_with(value: []const u8, prefix: []const u8) bool
```

[Source](../../compiler/std/bytes/bytes.dyn#L26)

```dyn
pub fn ends_with(value: []const u8, suffix: []const u8) bool
```

[Source](../../compiler/std/bytes/bytes.dyn#L30)

```dyn
pub fn find_byte(value: []const u8, byte: u8) isize
```

[Source](../../compiler/std/bytes/bytes.dyn#L39)

```dyn
pub fn find_last_byte(value: []const u8, byte: u8) isize
```

[Source](../../compiler/std/bytes/bytes.dyn#L48)

```dyn
pub fn find(value: []const u8, needle: []const u8) isize
```

[Source](../../compiler/std/bytes/bytes.dyn#L59)

```dyn
pub fn find_last(value: []const u8, needle: []const u8) isize
```

[Source](../../compiler/std/bytes/bytes.dyn#L70)

```dyn
pub fn contains(value: []const u8, needle: []const u8) bool
```

[Source](../../compiler/std/bytes/bytes.dyn#L72)

```dyn
pub fn count_occurrences(value: []const u8, needle: []const u8) usize
```

[Source](../../compiler/std/bytes/bytes.dyn#L85)

```dyn
pub struct Splitter {
  value: []const u8,
  separator: []const u8,
  offset: usize,
  done: bool,
}
```

[Source](../../compiler/std/bytes/bytes.dyn#L92)

```dyn
pub fn splitter(value: []const u8, separator: []const u8) Splitter
```

[Source](../../compiler/std/bytes/bytes.dyn#L97)

```dyn
pub fn split_next(state: *Splitter, output: *[]const u8) bool
```

[Source](../../compiler/std/bytes/bytes.dyn#L112)

```dyn
pub struct Cursor {
  data: []const u8,
  offset: usize,
}
```

[Source](../../compiler/std/bytes/bytes.dyn#L117)

```dyn
pub fn cursor(data: []const u8) Cursor
```

[Source](../../compiler/std/bytes/bytes.dyn#L118)

```dyn
pub fn cursor_remaining(state: *const Cursor) usize
```

[Source](../../compiler/std/bytes/bytes.dyn#L119)

```dyn
pub fn cursor_rest(state: *const Cursor) []const u8
```

[Source](../../compiler/std/bytes/bytes.dyn#L121)

```dyn
pub fn cursor_read(state: *Cursor, destination: []u8) usize
```

[Source](../../compiler/std/bytes/bytes.dyn#L133)

```dyn
pub fn cursor_skip(state: *Cursor, amount: usize) bool
```

[Source](../../compiler/std/bytes/bytes.dyn#L139)

```dyn
pub struct Builder {
  data: []u8,
  length: usize,
  failed: bool,
}
```

[Source](../../compiler/std/bytes/bytes.dyn#L145)

```dyn
pub fn builder(storage: []u8) Builder
```

[Source](../../compiler/std/bytes/bytes.dyn#L149)

```dyn
pub fn builder_bytes(state: *const Builder) []const u8
```

[Source](../../compiler/std/bytes/bytes.dyn#L150)

```dyn
pub fn builder_remaining(state: *const Builder) usize
```

[Source](../../compiler/std/bytes/bytes.dyn#L152)

```dyn
pub fn builder_write(state: *Builder, value: []const u8) bool
```

[Source](../../compiler/std/bytes/bytes.dyn#L166)

```dyn
pub fn builder_write_byte(state: *Builder, value: u8) bool
```

[Source](../../compiler/std/bytes/bytes.dyn#L176)

```dyn
pub fn builder_reset(state: *Builder)
```

[Source](../../compiler/std/bytes/bytes.dyn#L182)

Empty slices never overlap. Uses differences so address addition cannot overflow.

```dyn
pub fn overlaps(left: []const u8, right: []const u8) bool
```
