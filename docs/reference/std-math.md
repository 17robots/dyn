# std/math

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

## Source: compiler/std/math/math.dyn

[Source](../../compiler/std/math/math.dyn#L1)

```dyn
pub struct U64Result { value: u64, ok: bool }
```

[Source](../../compiler/std/math/math.dyn#L3)

```dyn
pub fn min_i64(a, b: i64) i64
```

[Source](../../compiler/std/math/math.dyn#L4)

```dyn
pub fn max_i64(a, b: i64) i64
```

[Source](../../compiler/std/math/math.dyn#L5)

```dyn
pub fn min_u64(a, b: u64) u64
```

[Source](../../compiler/std/math/math.dyn#L6)

```dyn
pub fn max_u64(a, b: u64) u64
```

[Source](../../compiler/std/math/math.dyn#L7)

```dyn
pub fn clamp_i64(value, minimum, maximum: i64) i64
```

[Source](../../compiler/std/math/math.dyn#L13)

```dyn
pub fn abs_i64(value: i64) i64
```

[Source](../../compiler/std/math/math.dyn#L18)

```dyn
pub fn gcd_u64(a_value, b_value: u64) u64
```

[Source](../../compiler/std/math/math.dyn#L23)

```dyn
pub fn checked_add_u64(a, b: u64) U64Result
```

[Source](../../compiler/std/math/math.dyn#L28)

```dyn
pub fn checked_mul_u64(a, b: u64) U64Result
```

[Source](../../compiler/std/math/math.dyn#L33)

```dyn
pub fn lcm_u64(a, b: u64) U64Result
```

[Source](../../compiler/std/math/math.dyn#L37)

```dyn
pub fn pow_u64(base_value, exponent_value: u64) U64Result
```

[Source](../../compiler/std/math/math.dyn#L54)

```dyn
pub fn sqrt_u64(value: u64) u64
```

[Source](../../compiler/std/math/math.dyn#L64)

```dyn
pub fn sign_i64(value: i64) i64
```
