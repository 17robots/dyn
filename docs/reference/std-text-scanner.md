# std/text/scanner

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

## Source: compiler/std/text/scanner/scanner.dyn

[Source](../../compiler/std/text/scanner/scanner.dyn#L1)

```dyn
pub struct Scanner { source: []const u8, offset: usize, line: usize, column: usize }
```

[Source](../../compiler/std/text/scanner/scanner.dyn#L3)

```dyn
pub fn scanner(source: []const u8) Scanner
```

[Source](../../compiler/std/text/scanner/scanner.dyn#L7)

```dyn
pub fn finished(state: *const Scanner) bool
```

[Source](../../compiler/std/text/scanner/scanner.dyn#L8)

```dyn
pub fn rest(state: *const Scanner) []const u8
```

[Source](../../compiler/std/text/scanner/scanner.dyn#L10)

```dyn
pub fn advance(state: *Scanner, amount: usize) bool
```

[Source](../../compiler/std/text/scanner/scanner.dyn#L21)

```dyn
pub fn next_line(state: *Scanner, output: *[]const u8) bool
```

[Source](../../compiler/std/text/scanner/scanner.dyn#L32)

```dyn
pub fn next_field(state: *Scanner, output: *[]const u8) bool
```
