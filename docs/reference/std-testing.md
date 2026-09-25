# std/testing

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/assert-message/main.dyn](../../tests/assert-message/main.dyn)
- [tests/environment-contracts/main.dyn](../../tests/environment-contracts/main.dyn)
- [tests/sdk-boundaries/main.dyn](../../tests/sdk-boundaries/main.dyn)
- [tests/sdk-property/main.dyn](../../tests/sdk-property/main.dyn)
- [tests/sdk-temporary/main.dyn](../../tests/sdk-temporary/main.dyn)
- [tests/sdk-tools/main.dyn](../../tests/sdk-tools/main.dyn)
- [tests/sdk-watch/main.dyn](../../tests/sdk-watch/main.dyn)
- [tests/stdlib-app/main.dyn](../../tests/stdlib-app/main.dyn)
- [tests/stdlib-dynlib/main.dyn](../../tests/stdlib-dynlib/main.dyn)
- [tests/stdlib-net-event/main.dyn](../../tests/stdlib-net-event/main.dyn)
- [tests/stdlib-profile/main.dyn](../../tests/stdlib-profile/main.dyn)
- [tests/stdlib-testing/main.dyn](../../tests/stdlib-testing/main.dyn)
- [tests/stdlib-tls/main.dyn](../../tests/stdlib-tls/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/testing/property.dyn

[Source](../../compiler/std/testing/property.dyn#L1)

```dyn
pub struct PropertyOptions { seed: u64, cases: usize, shrink_checks: usize }
```

[Source](../../compiler/std/testing/property.dyn#L2)

```dyn
pub struct PropertyResult {
  passed: bool, seed: u64, iteration: usize, example: []const u8,
  checks: usize, shrink_exhausted: bool,
}
```

[Source](../../compiler/std/testing/property.dyn#L10)

Property must be deterministic and must not retain its input. Work is split
into sample/trial halves; its half-length is the maximum generated input size.
A failure's minimized example borrows work. Reproduction requires the same
seed, iteration, work capacity, and deterministic predicate.

```dyn
pub fn check_property(options: PropertyOptions, work: []u8,
  predicate: *fn(rawptr, []const u8) bool, context: rawptr) PropertyResult
```

## Source: compiler/std/testing/temporary.dyn

[Source](../../compiler/std/testing/temporary.dyn#L2)

```dyn
pub struct TemporaryDirectory { path: []const u8, active: bool }
```

[Source](../../compiler/std/testing/temporary.dyn#L3)

```dyn
pub struct TemporaryResult { directory: TemporaryDirectory, error: isize, ok: bool }
```

[Source](../../compiler/std/testing/temporary.dyn#L5)

Reserves a private 0700 directory. The returned path borrows destination.

```dyn
pub fn temporary_directory(destination: []u8, prefix: []const u8) TemporaryResult
```

[Source](../../compiler/std/testing/temporary.dyn#L18)

```dyn
pub fn remove_temporary(directory: *TemporaryDirectory, frames: []fs.RemovalFrame, scratch: []u8) fs.Result
```

## Source: compiler/std/testing/testing.dyn

[Source](../../compiler/std/testing/testing.dyn#L6)

```dyn
pub fn expect(condition: bool, message: []const u8)
```

[Source](../../compiler/std/testing/testing.dyn#L7)

```dyn
pub fn expect_false(condition: bool, message: []const u8)
```

[Source](../../compiler/std/testing/testing.dyn#L8)

```dyn
pub fn equal_bytes(left: []const u8, right: []const u8) bool
```

[Source](../../compiler/std/testing/testing.dyn#L13)

```dyn
pub fn expect_equal_bytes(left: []const u8, right: []const u8, message: []const u8)
```

[Source](../../compiler/std/testing/testing.dyn#L14)

```dyn
pub fn expect_equal_i64(left: i64, right: i64, message: []const u8)
```

[Source](../../compiler/std/testing/testing.dyn#L15)

```dyn
pub fn expect_equal_u64(left: u64, right: u64, message: []const u8)
```

[Source](../../compiler/std/testing/testing.dyn#L16)

```dyn
pub fn expect_equal_usize(left: usize, right: usize, message: []const u8)
```

[Source](../../compiler/std/testing/testing.dyn#L17)

```dyn
pub fn expect_equal_isize(left: isize, right: isize, message: []const u8)
```

[Source](../../compiler/std/testing/testing.dyn#L18)

```dyn
pub fn expect_equal_bool(left: bool, right: bool, message: []const u8)
```

[Source](../../compiler/std/testing/testing.dyn#L20)

```dyn
pub struct Random { state: u64 }
```

[Source](../../compiler/std/testing/testing.dyn#L21)

```dyn
pub fn random(seed_value: u64) Random
```

[Source](../../compiler/std/testing/testing.dyn#L25)

```dyn
pub fn random_next(generator: *Random) u64
```

[Source](../../compiler/std/testing/testing.dyn#L30)

```dyn
pub fn random_below(generator: *Random, bound: usize) usize
```

[Source](../../compiler/std/testing/testing.dyn#L35)

```dyn
pub struct Benchmark { started: clock.Instant, iterations: usize }
```

[Source](../../compiler/std/testing/testing.dyn#L36)

```dyn
pub fn benchmark_start(iterations: usize) Benchmark
```

[Source](../../compiler/std/testing/testing.dyn#L37)

```dyn
pub fn benchmark_elapsed(benchmark: *const Benchmark) i64
```

[Source](../../compiler/std/testing/testing.dyn#L42)

```dyn
pub fn benchmark_nanoseconds_each(benchmark: *const Benchmark) i64
```

[Source](../../compiler/std/testing/testing.dyn#L50)

```dyn
pub fn temporary_path(destination: []u8, prefix: []const u8, suffix: []const u8) []u8
```
