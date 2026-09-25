# std/thread

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/release-concurrency/main.dyn](../../tests/release-concurrency/main.dyn)
- [tests/sdk-http-workers/main.dyn](../../tests/sdk-http-workers/main.dyn)
- [tests/stdlib-thread/main.dyn](../../tests/stdlib-thread/main.dyn)
- [tests/thread-aarch64/main.dyn](../../tests/thread-aarch64/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/thread/thread.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/thread/thread.dyn#L5)

```dyn
pub struct Thread { tid: sync.AtomicU32 }
```

[Source](../../compiler/std/thread/thread.dyn#L15)

```dyn
pub fn spawn(thread: *Thread, stack: []u8, entry: *fn(rawptr) isize, context: rawptr) isize
```

[Source](../../compiler/std/thread/thread.dyn#L21)

```dyn
pub fn join(thread: *Thread) isize
```

[Source](../../compiler/std/thread/thread.dyn#L31)

```dyn
pub fn id(thread: *const Thread) u32
```

[Source](../../compiler/std/thread/thread.dyn#L32)

```dyn
pub fn yield_now() isize
```
