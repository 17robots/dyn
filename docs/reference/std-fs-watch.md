# std/fs/watch

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-watch/main.dyn](../../tests/sdk-watch/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/fs/watch/watch.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/fs/watch/watch.dyn#L5)

```dyn
pub const Modify: u32 = 2
```

[Source](../../compiler/std/fs/watch/watch.dyn#L6)

```dyn
pub const Attributes: u32 = 4
```

[Source](../../compiler/std/fs/watch/watch.dyn#L7)

```dyn
pub const CloseWrite: u32 = 8
```

[Source](../../compiler/std/fs/watch/watch.dyn#L8)

```dyn
pub const MoveFrom: u32 = 64
```

[Source](../../compiler/std/fs/watch/watch.dyn#L9)

```dyn
pub const MoveTo: u32 = 128
```

[Source](../../compiler/std/fs/watch/watch.dyn#L10)

```dyn
pub const Create: u32 = 256
```

[Source](../../compiler/std/fs/watch/watch.dyn#L11)

```dyn
pub const Delete: u32 = 512
```

[Source](../../compiler/std/fs/watch/watch.dyn#L12)

```dyn
pub const DeleteSelf: u32 = 1024
```

[Source](../../compiler/std/fs/watch/watch.dyn#L13)

```dyn
pub const MoveSelf: u32 = 2048
```

[Source](../../compiler/std/fs/watch/watch.dyn#L14)

```dyn
pub const Ignored: u32 = 32768
```

[Source](../../compiler/std/fs/watch/watch.dyn#L15)

```dyn
pub const IsDirectory: u32 = 1073741824
```

[Source](../../compiler/std/fs/watch/watch.dyn#L16)

```dyn
pub const Changes: u32 = 4046
```

[Source](../../compiler/std/fs/watch/watch.dyn#L17)

```dyn
pub enum Status { Event, Empty, Error }
```

[Source](../../compiler/std/fs/watch/watch.dyn#L18)

```dyn
pub struct Watcher { descriptor: isize, storage: []u8, used: usize, offset: usize, rescan_required: bool }
```

[Source](../../compiler/std/fs/watch/watch.dyn#L19)

```dyn
pub struct OpenResult { watcher: Watcher, error: isize, ok: bool }
```

[Source](../../compiler/std/fs/watch/watch.dyn#L20)

```dyn
pub struct Result { value: i32, error: isize, ok: bool }
```

[Source](../../compiler/std/fs/watch/watch.dyn#L21)

```dyn
pub struct Event { watch: i32, mask: u32, cookie: u32, name: []const u8, rescan: bool }
```

[Source](../../compiler/std/fs/watch/watch.dyn#L22)

```dyn
pub struct EventResult { event: Event, status: Status, error: isize }
```

[Source](../../compiler/std/fs/watch/watch.dyn#L26)

Watches are non-recursive. Register each directory explicitly. Names borrow
storage until next refill. An overflow invalidates all cached workspace state.

```dyn
pub fn open(storage: []u8) OpenResult
```

[Source](../../compiler/std/fs/watch/watch.dyn#L32)

```dyn
pub fn add(state: *Watcher, path: []const u8, mask: u32) Result
```

[Source](../../compiler/std/fs/watch/watch.dyn#L39)

```dyn
pub fn remove(state: *Watcher, watch: i32) Result
```

[Source](../../compiler/std/fs/watch/watch.dyn#L43)

```dyn
pub fn close(state: *Watcher) Result
```

[Source](../../compiler/std/fs/watch/watch.dyn#L51)

```dyn
pub fn next(state: *Watcher) EventResult
```

[Source](../../compiler/std/fs/watch/watch.dyn#L79)

Call only after rebuilding the snapshot; events may continue arriving during
that scan, so drain/reconcile them before treating the workspace as current.

```dyn
pub fn acknowledge_rescan(state: *Watcher)
```
