# std/time

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-system/main.dyn](../../tests/sdk-system/main.dyn)
- [tests/stdlib-runtime/main.dyn](../../tests/stdlib-runtime/main.dyn)
- [tests/stdlib-str/main.dyn](../../tests/stdlib-str/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/time/time.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/time/time.dyn#L3)

```dyn
pub const Nanosecond: i64 = 1
```

[Source](../../compiler/std/time/time.dyn#L4)

```dyn
pub const Microsecond: i64 = 1000
```

[Source](../../compiler/std/time/time.dyn#L5)

```dyn
pub const Millisecond: i64 = 1000000
```

[Source](../../compiler/std/time/time.dyn#L6)

```dyn
pub const Second: i64 = 1000000000
```

[Source](../../compiler/std/time/time.dyn#L7)

```dyn
pub const Minute: i64 = 60000000000
```

[Source](../../compiler/std/time/time.dyn#L8)

```dyn
pub const Hour: i64 = 3600000000000
```

[Source](../../compiler/std/time/time.dyn#L10)

```dyn
pub struct Instant { seconds: i64, nanoseconds: i64 }
```

[Source](../../compiler/std/time/time.dyn#L11)

```dyn
pub struct DurationResult { value: i64, ok: bool }
```

[Source](../../compiler/std/time/time.dyn#L12)

```dyn
pub struct Deadline { at: Instant }
```

[Source](../../compiler/std/time/time.dyn#L13)

```dyn
pub struct DateTime {
  year: i32, month: u8, day: u8,
  hour: u8, minute: u8, second: u8,
  nanosecond: u32,
}
```

[Source](../../compiler/std/time/time.dyn#L19)

```dyn
pub fn checked_add(a, b: i64) DurationResult
```

[Source](../../compiler/std/time/time.dyn#L24)

```dyn
pub fn checked_sub(a, b: i64) DurationResult
```

[Source](../../compiler/std/time/time.dyn#L31)

```dyn
pub fn elapsed(start, end: Instant) DurationResult
```

[Source](../../compiler/std/time/time.dyn#L40)

```dyn
pub fn monotonic_now() Instant
```

[Source](../../compiler/std/time/time.dyn#L45)

```dyn
pub fn realtime_now() Instant
```

[Source](../../compiler/std/time/time.dyn#L50)

```dyn
pub fn sleep(duration: i64) bool
```

[Source](../../compiler/std/time/time.dyn#L58)

```dyn
pub fn deadline_after(duration: i64) Deadline
```

[Source](../../compiler/std/time/time.dyn#L65)

```dyn
pub fn deadline_expired(deadline: *const Deadline) bool
```

[Source](../../compiler/std/time/time.dyn#L70)

```dyn
pub fn deadline_remaining(deadline: *const Deadline) i64
```

[Source](../../compiler/std/time/time.dyn#L78)

```dyn
pub fn valid(value: *const DateTime) bool
```

[Source](../../compiler/std/time/time.dyn#L89)

```dyn
pub fn format_iso8601(destination: []u8, value: *const DateTime) []u8
```

[Source](../../compiler/std/time/time.dyn#L106)

```dyn
pub fn parse_iso8601(input: []const u8, output: *DateTime) bool
```
