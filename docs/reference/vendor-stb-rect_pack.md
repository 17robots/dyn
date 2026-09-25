# vendor/stb/rect_pack

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/stb-example/main.dyn](../../projects/stb-example/main.dyn), [tests/vendor-extra.py](../../tests/vendor-extra.py), [tests/vendor-stb-native.c](../../tests/vendor-stb-native.c)

## Declarations and source contracts

## Source: compiler/vendor/stb/rect_pack/rect_pack.dyn

[Source](../../compiler/vendor/stb/rect_pack/rect_pack.dyn#L5)

Integer skyline packing, no rotation. Caller owns rectangles; scratch arena is
rewound before return. Inputs must not overlap newly allocated scratch storage.

```dyn
pub struct Rectangle { width: i32, height: i32, x: i32, y: i32, packed: i32 }
```

[Source](../../compiler/vendor/stb/rect_pack/rect_pack.dyn#L7)

code=-1 invalid input/storage, 0 partial fit, 1 all fit. packed counts successes.

```dyn
pub struct Result { packed: usize, code: i32, ok: bool }
```

[Source](../../compiler/vendor/stb/rect_pack/rect_pack.dyn#L8)

```dyn
pub fn pack(scratch: *mem.Arena, width: i32, height: i32, rectangles: []Rectangle) Result
```
