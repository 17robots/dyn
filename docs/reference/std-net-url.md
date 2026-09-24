# std/net/url

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-boundaries/main.dyn](../../tests/sdk-boundaries/main.dyn)
- [tests/sdk-data/main.dyn](../../tests/sdk-data/main.dyn)
- [tests/stdlib-data/main.dyn](../../tests/stdlib-data/main.dyn)
- [tests/stdlib-foundation/main.dyn](../../tests/stdlib-foundation/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/net/url/url.dyn

[Source](../../compiler/std/net/url/url.dyn#L1)

```dyn
pub struct URL {
  scheme: []const u8,
  authority: []const u8,
  path: []const u8,
  query: []const u8,
  fragment: []const u8,
}
```

[Source](../../compiler/std/net/url/url.dyn#L9)

```dyn
pub struct ParseResult { value: URL, ok: bool, error_offset: usize }
```

[Source](../../compiler/std/net/url/url.dyn#L11)

```dyn
pub fn parse(text: []const u8) ParseResult
```

[Source](../../compiler/std/net/url/url.dyn#L57)

```dyn
pub struct EncodingResult { data: []u8, ok: bool }
```

[Source](../../compiler/std/net/url/url.dyn#L70)

Encode one component, including slashes. Source and destination must not overlap.
Capacity/validation failures leave destination unchanged.

```dyn
pub fn percent_encode(destination: []u8, source: []const u8) EncodingResult
```

[Source](../../compiler/std/net/url/url.dyn#L92)

Percent decoding treats '+' literally; it is not form-urlencoded decoding.

```dyn
pub fn percent_decode(destination: []u8, source: []const u8) EncodingResult
```
