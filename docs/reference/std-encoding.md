# std/encoding

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/encoding/encoding.dyn

[Source](../../compiler/std/encoding/encoding.dyn#L3)

Shared byte-codec result. Failure returns an empty data slice; required is
exact when input is valid and representable. No output is modified on failure.

```dyn
pub enum ErrorKind { None, InvalidInput, Capacity, Overflow, Overlap }
```

[Source](../../compiler/std/encoding/encoding.dyn#L4)

```dyn
pub struct Result { data: []u8, error: ErrorKind, required: usize, ok: bool }
```
