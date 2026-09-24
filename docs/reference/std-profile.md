# std/profile

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-depth/main.dyn](../../tests/sdk-depth/main.dyn)
- [tests/sdk-memory-observation/main.dyn](../../tests/sdk-memory-observation/main.dyn)
- [tests/stdlib-profile/main.dyn](../../tests/stdlib-profile/main.dyn)

Reviewed behavioral fixtures: [tests/sdk-memory-observation/main.dyn](../../tests/sdk-memory-observation/main.dyn)

## Declarations and source contracts

## Source: compiler/std/profile/profile.dyn

[Source](../../compiler/std/profile/profile.dyn#L4)

Caller-backed monotonic profiling. Event names are borrowed.

```dyn
pub struct Event {
  name: []const u8,
  started_nanoseconds: i64,
  duration_nanoseconds: i64,
}
```

[Source](../../compiler/std/profile/profile.dyn#L10)

```dyn
pub struct Span { name: []const u8, started: clock.Instant }
```

[Source](../../compiler/std/profile/profile.dyn#L12)

```dyn
pub struct Trace {
  events: []Event,
  count: usize,
  dropped: usize,
}
```

[Source](../../compiler/std/profile/profile.dyn#L18)

```dyn
pub fn trace(events: []Event) Trace
```

[Source](../../compiler/std/profile/profile.dyn#L22)

```dyn
pub fn begin(name: []const u8) Span
```

[Source](../../compiler/std/profile/profile.dyn#L26)

```dyn
pub fn finish(destination: *Trace, span: Span) bool
```

[Source](../../compiler/std/profile/profile.dyn#L43)

```dyn
pub fn recorded(value: *Trace) []Event
```

[Source](../../compiler/std/profile/profile.dyn#L44)

```dyn
pub fn clear(value: *Trace)
```
