# std/encoding/ini

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-data/main.dyn](../../tests/sdk-data/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/encoding/ini/ini.dyn

[Source](../../compiler/std/encoding/ini/ini.dyn#L3)

Allocation-free INI scanner. Names and values borrow the input.

```dyn
pub enum Kind { Section, Pair }
```

[Source](../../compiler/std/encoding/ini/ini.dyn#L4)

```dyn
pub enum ErrorKind { None, Syntax }
```

[Source](../../compiler/std/encoding/ini/ini.dyn#L5)

```dyn
pub struct Entry { section: []const u8, key: []const u8, value: []const u8, kind: Kind, line: usize }
```

[Source](../../compiler/std/encoding/ini/ini.dyn#L6)

```dyn
pub struct Scanner { source: []const u8, offset: usize, line: usize, section: []const u8, error: ErrorKind }
```

[Source](../../compiler/std/encoding/ini/ini.dyn#L7)

```dyn
pub struct Result { entry: Entry, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/encoding/ini/ini.dyn#L9)

```dyn
pub fn scanner(source: []const u8) Scanner
```

[Source](../../compiler/std/encoding/ini/ini.dyn#L18)

```dyn
pub fn next(state: *Scanner) Result
```

[Source](../../compiler/std/encoding/ini/ini.dyn#L50)

```dyn
pub fn find(source: []const u8, section: []const u8, key: []const u8) []const u8
```
