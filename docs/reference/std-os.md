# std/os

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

## Source: compiler/std/os/os.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/os/os.dyn#L4)

Stable system-facing values. Platform implementation remains isolated below os/linux.

```dyn
pub const Name: []const u8 = "linux"
```

[Source](../../compiler/std/os/os.dyn#L5)

```dyn
pub const PathSeparator: u8 = '/'
```

[Source](../../compiler/std/os/os.dyn#L6)

```dyn
pub const has_processes: bool = true
```

[Source](../../compiler/std/os/os.dyn#L7)

```dyn
pub const has_memory_mapping: bool = true
```
