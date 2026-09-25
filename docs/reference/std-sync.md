# std/sync

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
- [tests/sdk-tools/main.dyn](../../tests/sdk-tools/main.dyn)
- [tests/stdlib-thread/main.dyn](../../tests/stdlib-thread/main.dyn)
- [tests/thread-aarch64/main.dyn](../../tests/thread-aarch64/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/sync/sync.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/sync/sync.dyn#L3)

```dyn
pub struct AtomicU32 { value: u32 }
```

[Source](../../compiler/std/sync/sync.dyn#L4)

```dyn
pub struct AtomicU64 { value: u64 }
```

[Source](../../compiler/std/sync/sync.dyn#L17)

```dyn
pub fn atomic_u32(value: u32) AtomicU32
```

[Source](../../compiler/std/sync/sync.dyn#L18)

```dyn
pub fn atomic_u64(value: u64) AtomicU64
```

[Source](../../compiler/std/sync/sync.dyn#L19)

```dyn
pub fn load_u32(value: *const AtomicU32) u32
```

[Source](../../compiler/std/sync/sync.dyn#L20)

```dyn
pub fn store_u32(value: *AtomicU32, desired: u32)
```

[Source](../../compiler/std/sync/sync.dyn#L21)

```dyn
pub fn exchange_u32(value: *AtomicU32, desired: u32) u32
```

[Source](../../compiler/std/sync/sync.dyn#L22)

```dyn
pub fn fetch_add_u32(value: *AtomicU32, amount: u32) u32
```

[Source](../../compiler/std/sync/sync.dyn#L23)

```dyn
pub fn compare_exchange_u32(value: *AtomicU32, expected: u32, desired: u32) bool
```

[Source](../../compiler/std/sync/sync.dyn#L24)

```dyn
pub fn load_u64(value: *const AtomicU64) u64
```

[Source](../../compiler/std/sync/sync.dyn#L25)

```dyn
pub fn store_u64(value: *AtomicU64, desired: u64)
```

[Source](../../compiler/std/sync/sync.dyn#L26)

```dyn
pub fn exchange_u64(value: *AtomicU64, desired: u64) u64
```

[Source](../../compiler/std/sync/sync.dyn#L27)

```dyn
pub fn fetch_add_u64(value: *AtomicU64, amount: u64) u64
```

[Source](../../compiler/std/sync/sync.dyn#L28)

```dyn
pub fn compare_exchange_u64(value: *AtomicU64, expected: u64, desired: u64) bool
```

[Source](../../compiler/std/sync/sync.dyn#L31)

```dyn
pub struct Mutex { state: AtomicU32 }
```

[Source](../../compiler/std/sync/sync.dyn#L33)

```dyn
pub fn mutex() Mutex
```

[Source](../../compiler/std/sync/sync.dyn#L35)

```dyn
pub fn try_lock(value: *Mutex) bool
```

[Source](../../compiler/std/sync/sync.dyn#L39)

```dyn
pub fn lock(value: *Mutex)
```

[Source](../../compiler/std/sync/sync.dyn#L48)

```dyn
pub fn unlock(value: *Mutex)
```

[Source](../../compiler/std/sync/sync.dyn#L55)

```dyn
pub struct Condition { sequence: AtomicU32 }
```

[Source](../../compiler/std/sync/sync.dyn#L56)

```dyn
pub struct Semaphore { count: AtomicU32 }
```

[Source](../../compiler/std/sync/sync.dyn#L57)

```dyn
pub struct Once { state: AtomicU32 }
```

[Source](../../compiler/std/sync/sync.dyn#L59)

```dyn
pub fn condition() Condition
```

[Source](../../compiler/std/sync/sync.dyn#L62)

Mutex must be held on entry. Spurious wakeups are allowed: always wait in a predicate loop.

```dyn
pub fn condition_wait(value: *Condition, lock_value: *Mutex)
```

[Source](../../compiler/std/sync/sync.dyn#L70)

```dyn
pub fn condition_signal(value: *Condition)
```

[Source](../../compiler/std/sync/sync.dyn#L74)

```dyn
pub fn condition_broadcast(value: *Condition)
```

[Source](../../compiler/std/sync/sync.dyn#L79)

```dyn
pub fn semaphore(count: u32) Semaphore
```

[Source](../../compiler/std/sync/sync.dyn#L80)

```dyn
pub fn semaphore_try_wait(value: *Semaphore) bool
```

[Source](../../compiler/std/sync/sync.dyn#L88)

```dyn
pub fn semaphore_wait(value: *Semaphore)
```

[Source](../../compiler/std/sync/sync.dyn#L91)

```dyn
pub fn semaphore_post(value: *Semaphore)
```

[Source](../../compiler/std/sync/sync.dyn#L96)

```dyn
pub fn once() Once
```

[Source](../../compiler/std/sync/sync.dyn#L98)

Returns true exactly once. Winner calls initializer then `once_complete`.

```dyn
pub fn once_begin(value: *Once) bool
```

[Source](../../compiler/std/sync/sync.dyn#L103)

```dyn
pub fn once_complete(value: *Once)
```
