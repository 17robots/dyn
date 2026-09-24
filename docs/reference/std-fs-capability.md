# std/fs/capability

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

## Source: compiler/std/fs/capability/capability.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/fs/capability/capability.dyn#L8)

A borrowed directory descriptor limits file lookup through this interface.
Descriptor owner keeps it open; do not close/reuse it while a capability exists.
This is not a sandbox for native code with unrestricted syscall access.

```dyn
pub struct Directory { descriptor: isize = -1, events: *observe.Log, resource: u64 }
```

[Source](../../compiler/std/fs/capability/capability.dyn#L9)

```dyn
pub enum ReadResult { Read: usize, Failed: isize }
```

[Source](../../compiler/std/fs/capability/capability.dyn#L17)

Kernel-enforced relative lookup: no absolute paths, parent escapes, symlinks or
magic links. Opens read-only, never follows final/intermediate symlinks, and closes
its temporary file descriptor before returning. No heap allocation.
Destination receives at most one read; partial reads are ordinary progress.
ENOSYS is reported on kernels lacking openat2; no insecure fallback.

```dyn
pub fn read(directory: *const Directory, path: []const u8, destination: []u8) ReadResult
```
