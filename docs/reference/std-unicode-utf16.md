# std/unicode/utf16

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-layout/main.dyn](../../tests/sdk-layout/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/unicode/utf16/utf16.dyn

[Source](../../compiler/std/unicode/utf16/utf16.dyn#L1)

```dyn
pub const Replacement: u32 = 65533
```

[Source](../../compiler/std/unicode/utf16/utf16.dyn#L3)

```dyn
pub struct Decode { codepoint: u32, width: usize, ok: bool }
```

[Source](../../compiler/std/unicode/utf16/utf16.dyn#L5)

```dyn
pub fn decode(source: []const u16, offset: usize) Decode
```

[Source](../../compiler/std/unicode/utf16/utf16.dyn#L19)

```dyn
pub fn encode(destination: []u16, codepoint: u32) usize
```

[Source](../../compiler/std/unicode/utf16/utf16.dyn#L33)

```dyn
pub fn valid(source: []const u16) bool
```

[Source](../../compiler/std/unicode/utf16/utf16.dyn#L43)

```dyn
pub fn codepoint_count(source: []const u16, output: *usize) bool
```
