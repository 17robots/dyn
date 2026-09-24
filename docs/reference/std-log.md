# std/log

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-cli/main.dyn](../../tests/sdk-cli/main.dyn)
- [tests/stdlib-contracts/main.dyn](../../tests/stdlib-contracts/main.dyn)
- [tests/stdlib-io/main.dyn](../../tests/stdlib-io/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/log/log.dyn

[Source](../../compiler/std/log/log.dyn#L3)

```dyn
pub enum Level { Debug, Info, Warning, Error }
```

[Source](../../compiler/std/log/log.dyn#L4)

```dyn
pub struct Field { name: []const u8, value: []const u8 }
```

[Source](../../compiler/std/log/log.dyn#L5)

```dyn
pub struct Logger { output: stream.Writer, minimum: Level }
```

[Source](../../compiler/std/log/log.dyn#L6)

```dyn
pub fn logger(output: stream.Writer, minimum: Level) Logger
```

[Source](../../compiler/std/log/log.dyn#L19)

```dyn
pub fn write(target: *Logger, level: Level, message: []const u8, fields: []const Field) stream.Result
```
