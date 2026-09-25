# std/flags

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-boundaries/main.dyn](../../tests/sdk-boundaries/main.dyn)
- [tests/sdk-buffer-contracts/main.dyn](../../tests/sdk-buffer-contracts/main.dyn)
- [tests/sdk-cli/main.dyn](../../tests/sdk-cli/main.dyn)
- [tests/stdlib-app/main.dyn](../../tests/stdlib-app/main.dyn)
- [tests/stdlib-cli/main.dyn](../../tests/stdlib-cli/main.dyn)
- [tests/stdlib-system/main.dyn](../../tests/stdlib-system/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/flags/flags.dyn

[Source](../../compiler/std/flags/flags.dyn#L6)

Allocation-free command-line parser. Definitions and returned strings are borrowed.

```dyn
pub enum Kind { Bool, String, Integer, Float, Choice }
```

[Source](../../compiler/std/flags/flags.dyn#L7)

```dyn
pub enum ErrorKind { None, Unknown, MissingValue, UnexpectedValue, Capacity, InvalidValue, Required, Overflow, Overlap }
```

[Source](../../compiler/std/flags/flags.dyn#L8)

```dyn
pub struct Option { name: []const u8, short: u8, kind: Kind, required: bool, default_value: []const u8, choices: [][]const u8 }
```

[Source](../../compiler/std/flags/flags.dyn#L9)

```dyn
pub struct Value { text: []const u8, present: bool, occurrences: usize }
```

[Source](../../compiler/std/flags/flags.dyn#L10)

```dyn
pub struct Error { kind: ErrorKind, argument: usize, option: []const u8 }
```

[Source](../../compiler/std/flags/flags.dyn#L11)

```dyn
pub struct Result { values: []Value, positionals: [][]const u8, error: Error, ok: bool }
```

[Source](../../compiler/std/flags/flags.dyn#L13)

```dyn
pub fn bool_option(name: []const u8, short: u8) Option
```

[Source](../../compiler/std/flags/flags.dyn#L16)

```dyn
pub fn string_option(name: []const u8, short: u8) Option
```

[Source](../../compiler/std/flags/flags.dyn#L33)

```dyn
pub fn parse(
  options: []const Option,
  arguments: [][]const u8,
  value_storage: []Value,
  positional_storage: [][]const u8,
) Result
```

[Source](../../compiler/std/flags/flags.dyn#L109)

```dyn
pub struct TextResult { value: []u8, error: ErrorKind, required: usize, ok: bool }
```

[Source](../../compiler/std/flags/flags.dyn#L146)

Failure writes nothing. Returned text borrows destination and excludes NUL.

```dyn
pub fn usage(destination: []u8, program: []const u8, options: []const Option) TextResult
```

[Source](../../compiler/std/flags/flags.dyn#L150)

```dyn
pub fn required_string_option(name: []const u8, short: u8) Option
```

[Source](../../compiler/std/flags/flags.dyn#L153)

```dyn
pub fn integer_option(name: []const u8, short: u8) Option
```

[Source](../../compiler/std/flags/flags.dyn#L156)

```dyn
pub fn float_option(name: []const u8, short: u8) Option
```

[Source](../../compiler/std/flags/flags.dyn#L159)

```dyn
pub fn choice_option(name: []const u8, short: u8, choices: [][]const u8) Option
```

[Source](../../compiler/std/flags/flags.dyn#L163)

One long-option candidate per line. Empty option lists succeed with empty text.

```dyn
pub fn completion(destination: []u8, options: []const Option) TextResult
```
