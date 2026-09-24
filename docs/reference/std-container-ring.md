# std/container/ring

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

## Source: compiler/std/container/ring/ring.dyn

[Source](../../compiler/std/container/ring/ring.dyn#L1)

```dyn
pub struct Ring {
  data: []u8,
  read: usize,
  length: usize,
}
```

[Source](../../compiler/std/container/ring/ring.dyn#L7)

```dyn
pub fn init(backing: []u8) Ring
```

[Source](../../compiler/std/container/ring/ring.dyn#L8)

```dyn
pub fn length(state: *const Ring) usize
```

[Source](../../compiler/std/container/ring/ring.dyn#L10)

```dyn
pub fn push(state: *Ring, byte: u8) bool
```

[Source](../../compiler/std/container/ring/ring.dyn#L17)

```dyn
pub fn pop(state: *Ring, output: *u8) bool
```
