# std/container/bit_set

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-tools/main.dyn](../../tests/sdk-tools/main.dyn)
- [tests/stdlib-mem-extra/main.dyn](../../tests/stdlib-mem-extra/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/container/bit_set/bit_set.dyn

[Source](../../compiler/std/container/bit_set/bit_set.dyn#L1)

```dyn
pub fn clear(words: []u64)
```

[Source](../../compiler/std/container/bit_set/bit_set.dyn#L6)

```dyn
pub fn get(words: []const u64, bit: usize) bool
```

[Source](../../compiler/std/container/bit_set/bit_set.dyn#L11)

```dyn
pub fn set(words: []u64, bit: usize, value: bool) bool
```
