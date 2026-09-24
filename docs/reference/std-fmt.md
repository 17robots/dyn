# std/fmt

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-boundaries/main.dyn](../../tests/sdk-boundaries/main.dyn)
- [tests/sdk-collections/main.dyn](../../tests/sdk-collections/main.dyn)
- [tests/sdk-foundation/main.dyn](../../tests/sdk-foundation/main.dyn)
- [tests/sdk-system/main.dyn](../../tests/sdk-system/main.dyn)
- [tests/sdk-temporary/main.dyn](../../tests/sdk-temporary/main.dyn)
- [tests/sdk-watch/main.dyn](../../tests/sdk-watch/main.dyn)
- [tests/stdlib-contracts/main.dyn](../../tests/stdlib-contracts/main.dyn)
- [tests/stdlib-io/main.dyn](../../tests/stdlib-io/main.dyn)
- [tests/stdlib-str/main.dyn](../../tests/stdlib-str/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/fmt/fmt.dyn

[Source](../../compiler/std/fmt/fmt.dyn#L3)

```dyn
pub struct Buffer { data: []u8, length: usize }
```

[Source](../../compiler/std/fmt/fmt.dyn#L4)

```dyn
pub fn buffer(storage: []u8) Buffer
```

[Source](../../compiler/std/fmt/fmt.dyn#L5)

```dyn
pub fn bytes(state: *const Buffer) []const u8
```

[Source](../../compiler/std/fmt/fmt.dyn#L6)

```dyn
pub fn remaining(state: *const Buffer) usize
```

[Source](../../compiler/std/fmt/fmt.dyn#L10)

```dyn
pub fn clear(state: *Buffer)
```

[Source](../../compiler/std/fmt/fmt.dyn#L12)

```dyn
pub fn write(state: *Buffer, value: []const u8) bool
```

[Source](../../compiler/std/fmt/fmt.dyn#L20)

```dyn
pub fn write_byte(state: *Buffer, value: u8) bool
```

[Source](../../compiler/std/fmt/fmt.dyn#L27)

```dyn
pub fn u64_base(destination: []u8, value: u64, base: u8, uppercase: bool) []u8
```

[Source](../../compiler/std/fmt/fmt.dyn#L47)

```dyn
pub fn u64_decimal(destination: []u8, value: u64) []u8
```

[Source](../../compiler/std/fmt/fmt.dyn#L51)

```dyn
pub fn i64_decimal(destination: []u8, value: i64) []u8
```

[Source](../../compiler/std/fmt/fmt.dyn#L64)

```dyn
pub fn write_u64(state: *Buffer, value: u64) bool
```

[Source](../../compiler/std/fmt/fmt.dyn#L69)

```dyn
pub fn write_i64(state: *Buffer, value: i64) bool
```

[Source](../../compiler/std/fmt/fmt.dyn#L74)

```dyn
pub fn write_bool(state: *Buffer, value: bool) bool
```

[Source](../../compiler/std/fmt/fmt.dyn#L79)

```dyn
pub fn write_padding(state: *Buffer, byte: u8, amount: usize) bool
```

[Source](../../compiler/std/fmt/fmt.dyn#L87)

```dyn
pub fn write_quoted(state: *Buffer, value: []const u8) bool
```

[Source](../../compiler/std/fmt/fmt.dyn#L123)

```dyn
pub fn write_arguments(state: *Buffer, arguments: []const any) bool
```

[Source](../../compiler/std/fmt/fmt.dyn#L150)

```dyn
pub fn write_values(state: *Buffer, values: ...any) bool
```

[Source](../../compiler/std/fmt/fmt.dyn#L157)

Rounded decimal formatting, not a shortest-roundtrip serialization format.
Up to 15 fractional digits; trailing zeroes are removed. Very small/large
magnitudes use a decimal exponent. Failure returns an empty slice.

```dyn
pub fn f64_decimal(destination: []u8, value: f64, precision: usize) []u8
```

[Source](../../compiler/std/fmt/fmt.dyn#L203)

```dyn
pub fn write_f64(state: *Buffer, value: f64) bool
```

[Source](../../compiler/std/fmt/fmt.dyn#L208)

```dyn
pub fn write_u64_width(state: *Buffer, value: u64, width: usize, padding: u8) bool
```
