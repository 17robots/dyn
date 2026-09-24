# std/semver

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-foundation/main.dyn](../../tests/sdk-foundation/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/semver/semver.dyn

[Source](../../compiler/std/semver/semver.dyn#L3)

```dyn
pub struct Version {
  major: u32,
  minor: u32,
  patch: u32,
  prerelease: []const u8,
  build: []const u8,
}
```

[Source](../../compiler/std/semver/semver.dyn#L11)

```dyn
pub struct ParseResult { version: Version, offset: usize, ok: bool }
```

[Source](../../compiler/std/semver/semver.dyn#L55)

```dyn
pub fn parse(text: []const u8) ParseResult
```

[Source](../../compiler/std/semver/semver.dyn#L134)

Build metadata does not affect precedence.

```dyn
pub fn compare(a, b: Version) i32
```

[Source](../../compiler/std/semver/semver.dyn#L141)

```dyn
pub struct Range {
  minimum: Version,
  maximum: Version,
  has_minimum: bool,
  has_maximum: bool,
  include_minimum: bool,
  include_maximum: bool,
}
```

[Source](../../compiler/std/semver/semver.dyn#L150)

```dyn
pub fn contains(range: *const Range, version: Version) bool
```
