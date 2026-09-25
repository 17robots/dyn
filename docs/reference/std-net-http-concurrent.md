# std/net/http/concurrent

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-http-workers/main.dyn](../../tests/sdk-http-workers/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/net/http/concurrent/concurrent.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/net/http/concurrent/concurrent.dyn#L8)

```dyn
pub struct Worker {
  thread: threading.Thread,
  listener: *http.Listener,
  handler: http.Handler,
  storage: []u8,
  error: http.Result,
  stopping: sync.AtomicU32,
  control: sync.Mutex,
  active_descriptor: isize,
  request_errors: usize,
}
```

[Source](../../compiler/std/net/http/concurrent/concurrent.dyn#L19)

```dyn
pub struct Result { started: usize, error: isize, ok: bool }
```

[Source](../../compiler/std/net/http/concurrent/concurrent.dyn#L51)

Call stop, then join, then close the listener. Never close it while workers run.
stop interrupts blocked accept/read/write, but cannot cancel arbitrary handler code.

```dyn
pub fn stop(workers: []Worker)
```

[Source](../../compiler/std/net/http/concurrent/concurrent.dyn#L65)

Backing storage/stacks must be disjoint and live through join. Workers must be
zero-initialized or already joined. Partial startup is stopped and drained.

```dyn
pub fn start(workers: []Worker, listener: *http.Listener, receive_storage: []u8,
  worker_storage_size: usize, stacks: []u8, stack_size: usize, handler: http.Handler) Result
```

[Source](../../compiler/std/net/http/concurrent/concurrent.dyn#L88)

Always attempts every join; a worker error never strands later live workers.

```dyn
pub fn join(workers: []Worker) Result
```
