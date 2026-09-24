# std/unicode/utf8

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-foundation/main.dyn](../../tests/sdk-foundation/main.dyn)
- [tests/stdlib-str/main.dyn](../../tests/stdlib-str/main.dyn)
- [tests/stdlib-text-extra/main.dyn](../../tests/stdlib-text-extra/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/unicode/utf8/utf8.dyn

[Source](../../compiler/std/unicode/utf8/utf8.dyn#L3)

```dyn
pub struct Decode {
  codepoint: u32,
  width: usize,
  ok: bool,
}
```

[Source](../../compiler/std/unicode/utf8/utf8.dyn#L9)

```dyn
pub fn decode(text: []const u8, offset: usize) Decode
```

[Source](../../compiler/std/unicode/utf8/utf8.dyn#L37)

```dyn
pub fn valid(text: []const u8) bool
```

[Source](../../compiler/std/unicode/utf8/utf8.dyn#L47)

```dyn
pub fn codepoint_count(text: []const u8, output: *usize) bool
```

[Source](../../compiler/std/unicode/utf8/utf8.dyn#L60)

```dyn
pub fn encoded_width(codepoint: u32) usize
```

[Source](../../compiler/std/unicode/utf8/utf8.dyn#L69)

```dyn
pub fn encode(destination: []u8, codepoint: u32) usize
```

[Source](../../compiler/std/unicode/utf8/utf8.dyn#L94)

```dyn
pub struct Iterator {
  text: []const u8,
  offset: usize,
}
```

[Source](../../compiler/std/unicode/utf8/utf8.dyn#L99)

```dyn
pub fn iterator(text: []const u8) Iterator
```

[Source](../../compiler/std/unicode/utf8/utf8.dyn#L101)

```dyn
pub fn next(state: *Iterator, output: *u32) bool
```
