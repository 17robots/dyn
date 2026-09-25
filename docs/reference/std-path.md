# std/path

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/path-contracts/main.dyn](../../tests/path-contracts/main.dyn)
- [tests/sdk-boundaries/main.dyn](../../tests/sdk-boundaries/main.dyn)
- [tests/sdk-system/main.dyn](../../tests/sdk-system/main.dyn)
- [tests/stdlib-app/main.dyn](../../tests/stdlib-app/main.dyn)
- [tests/stdlib-os-expanded/main.dyn](../../tests/stdlib-os-expanded/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/path/path.dyn

[Source](../../compiler/std/path/path.dyn#L4)

Slash-separated lexical paths. Operations do not access filesystem.

```dyn
pub struct Result { value: []u8, ok: bool }
```

[Source](../../compiler/std/path/path.dyn#L6)

```dyn
pub fn basename(path: []const u8) []const u8
```

[Source](../../compiler/std/path/path.dyn#L14)

```dyn
pub fn dirname(path: []const u8) []const u8
```

[Source](../../compiler/std/path/path.dyn#L22)

```dyn
pub fn extension(path: []const u8) []const u8
```

[Source](../../compiler/std/path/path.dyn#L28)

```dyn
pub fn is_absolute(path: []const u8) bool
```

[Source](../../compiler/std/path/path.dyn#L30)

```dyn
pub fn join(destination: []u8, left: []const u8, right: []const u8) Result
```

[Source](../../compiler/std/path/path.dyn#L44)

```dyn
pub fn clean(destination: []u8, path: []const u8) Result
```

[Source](../../compiler/std/path/path.dyn#L84)

```dyn
pub fn safe_join(destination: []u8, root: []const u8, child: []const u8) Result
```

[Source](../../compiler/std/path/path.dyn#L113)

```dyn
pub struct Components { text: []const u8, offset: usize }
```

[Source](../../compiler/std/path/path.dyn#L114)

```dyn
pub struct Component { value: []const u8, offset: usize, found: bool }
```

[Source](../../compiler/std/path/path.dyn#L115)

```dyn
pub fn components(text: []const u8) Components
```

[Source](../../compiler/std/path/path.dyn#L116)

```dyn
pub fn component_next(state: *Components) Component
```

[Source](../../compiler/std/path/path.dyn#L125)

Lexical relative path, for normalized inputs up to 4096 bytes each.
Absolute and relative roots cannot be mixed. No filesystem access occurs.

```dyn
pub fn relative(destination: []u8, base: []const u8, target: []const u8) Result
```
