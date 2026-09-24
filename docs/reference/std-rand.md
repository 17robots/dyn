# std/rand

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-foundation/main.dyn](../../tests/sdk-foundation/main.dyn)
- [tests/stdlib-foundation/main.dyn](../../tests/stdlib-foundation/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/rand/rand.dyn

[Source](../../compiler/std/rand/rand.dyn#L3)

```dyn
pub struct State { value: u64 }
```

[Source](../../compiler/std/rand/rand.dyn#L5)

```dyn
pub fn seeded(seed: u64) State
```

[Source](../../compiler/std/rand/rand.dyn#L11)

```dyn
pub fn next_u64(state: *State) u64
```

[Source](../../compiler/std/rand/rand.dyn#L17)

Unbiased result in [0, limit). Limits above generator range are rejected.

```dyn
pub fn below(state: *State, limit: u64, output: *u64) bool
```

[Source](../../compiler/std/rand/rand.dyn#L27)

```dyn
pub fn fill(state: *State, destination: []u8)
```
