# std/sort

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-foundation/main.dyn](../../tests/sdk-foundation/main.dyn)
- [tests/stdlib-core-extra/main.dyn](../../tests/stdlib-core-extra/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/sort/sort.dyn

[Source](../../compiler/std/sort/sort.dyn#L2)

Concrete scalar sorting until Dyn has an honest typed-collection story.

```dyn
pub struct SearchResult { index: usize, found: bool }
```

[Source](../../compiler/std/sort/sort.dyn#L14)

```dyn
pub fn i64s(values: []i64)
```

[Source](../../compiler/std/sort/sort.dyn#L26)

```dyn
pub fn search_i64(values: []const i64, target: i64) SearchResult
```

[Source](../../compiler/std/sort/sort.dyn#L45)

```dyn
pub fn u64s(values: []u64)
```

[Source](../../compiler/std/sort/sort.dyn#L57)

```dyn
pub fn search_u64(values: []const u64, target: u64) SearchResult
```
