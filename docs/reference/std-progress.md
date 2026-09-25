# std/progress

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-cli/main.dyn](../../tests/sdk-cli/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/progress/progress.dyn

[Source](../../compiler/std/progress/progress.dyn#L1)

```dyn
pub struct Node { name: []const u8, completed: u64, total: u64, active: bool }
```

[Source](../../compiler/std/progress/progress.dyn#L2)

```dyn
pub struct Progress { nodes: []Node, length: usize, dropped: usize }
```

[Source](../../compiler/std/progress/progress.dyn#L3)

```dyn
pub fn progress(storage: []Node) Progress
```

[Source](../../compiler/std/progress/progress.dyn#L4)

```dyn
pub fn begin(state: *Progress, name: []const u8, total: u64) usize
```

[Source](../../compiler/std/progress/progress.dyn#L10)

```dyn
pub fn advance(state: *Progress, index: usize, amount: u64) bool
```

[Source](../../compiler/std/progress/progress.dyn#L17)

```dyn
pub fn end(state: *Progress, index: usize) bool
```

[Source](../../compiler/std/progress/progress.dyn#L21)

```dyn
pub fn reset(state: *Progress)
```
