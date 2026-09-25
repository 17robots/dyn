# std/observe

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-observe/main.dyn](../../tests/sdk-observe/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/observe/observe.dyn

[Source](../../compiler/std/observe/observe.dyn#L3)

Optional, allocation-free runtime events. All text fields borrow caller storage.
Keep event backing and labels alive until consumers finish. Thread-confined.

```dyn
pub enum Kind { Allocated, AllocationFailed, Reclaimed, Released, ResourceOpened, ResourceClosed, Denied, Checkpoint }
```

[Source](../../compiler/std/observe/observe.dyn#L4)

```dyn
pub struct Event { kind: Kind, resource: u64, value: u64, source: []const u8, line: usize }
```

[Source](../../compiler/std/observe/observe.dyn#L5)

```dyn
pub struct Log { events: []Event, count: usize, dropped: usize }
```

[Source](../../compiler/std/observe/observe.dyn#L6)

```dyn
pub fn log(events: []Event) Log
```

[Source](../../compiler/std/observe/observe.dyn#L8)

Full logs drop new events; they never overwrite earlier events or allocate.

```dyn
pub fn record(destination: *Log, event: Event) bool
```

[Source](../../compiler/std/observe/observe.dyn#L17)

```dyn
pub fn recorded(value: *const Log) []const Event
```

[Source](../../compiler/std/observe/observe.dyn#L18)

```dyn
pub fn clear(value: *Log)
```
