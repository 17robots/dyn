# std/fs

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/directory-listing/main.dyn](../../tests/directory-listing/main.dyn)
- [tests/memory-runtime/main.dyn](../../tests/memory-runtime/main.dyn)
- [tests/sdk-system/main.dyn](../../tests/sdk-system/main.dyn)
- [tests/sdk-temporary/main.dyn](../../tests/sdk-temporary/main.dyn)
- [tests/sdk-watch/main.dyn](../../tests/sdk-watch/main.dyn)
- [tests/stdlib-app/main.dyn](../../tests/stdlib-app/main.dyn)
- [tests/stdlib-io/main.dyn](../../tests/stdlib-io/main.dyn)
- [tests/stdlib-net-event/main.dyn](../../tests/stdlib-net-event/main.dyn)
- [tests/stdlib-os-expanded/main.dyn](../../tests/stdlib-os-expanded/main.dyn)
- [tests/stdlib-process/main.dyn](../../tests/stdlib-process/main.dyn)
- [tests/stdlib-system/main.dyn](../../tests/stdlib-system/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/fs/fs.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/fs/fs.dyn#L12)

Linux file adapter behind portable-shaped results. Paths are borrowed UTF-8 bytes.
Construct through open/create, or borrow an existing descriptor explicitly.
File{} represents stdin, not an unopened handle. Copies do not duplicate ownership.

```dyn
pub struct File { descriptor: isize }
```

[Source](../../compiler/std/fs/fs.dyn#L13)

```dyn
pub struct FileResult { file: File, error: isize, ok: bool }
```

[Source](../../compiler/std/fs/fs.dyn#L14)

```dyn
pub struct Result { transferred: usize, error: isize, ok: bool }
```

[Source](../../compiler/std/fs/fs.dyn#L15)

```dyn
pub struct OffsetResult { offset: usize, error: isize, ok: bool }
```

[Source](../../compiler/std/fs/fs.dyn#L16)

```dyn
pub struct Metadata { size: u64, inode: u64, device: u64, mode: u16, error: isize, ok: bool }
```

[Source](../../compiler/std/fs/fs.dyn#L17)

```dyn
pub struct PathResult { path: []u8, error: isize, ok: bool }
```

[Source](../../compiler/std/fs/fs.dyn#L18)

```dyn
pub struct ReadAllResult { data: []u8, error: isize, ok: bool }
```

[Source](../../compiler/std/fs/fs.dyn#L19)

```dyn
pub enum AppDirectory { Home, Config, Cache, Data, Runtime }
```

[Source](../../compiler/std/fs/fs.dyn#L20)

```dyn
pub struct Directory {
  file: File,
  storage: []u8,
  offset: usize,
  used: usize,
}
```

[Source](../../compiler/std/fs/fs.dyn#L26)

```dyn
pub struct DirectoryResult { directory: Directory, error: isize, ok: bool }
```

[Source](../../compiler/std/fs/fs.dyn#L27)

```dyn
pub struct DirectoryEntry { name: []const u8, kind: u8, ok: bool, error: isize }
```

[Source](../../compiler/std/fs/fs.dyn#L45)

```dyn
pub fn open(path: []const u8) FileResult
```

[Source](../../compiler/std/fs/fs.dyn#L46)

```dyn
pub fn create(path: []const u8) FileResult
```

[Source](../../compiler/std/fs/fs.dyn#L47)

```dyn
pub fn append(path: []const u8) FileResult
```

[Source](../../compiler/std/fs/fs.dyn#L48)

```dyn
pub fn create_exclusive(path: []const u8) FileResult
```

[Source](../../compiler/std/fs/fs.dyn#L50)

```dyn
pub fn open_directory(path: []const u8, storage: []u8) DirectoryResult
```

[Source](../../compiler/std/fs/fs.dyn#L62)

Entry name borrows directory storage and may be invalidated by next refill.

```dyn
pub fn directory_next(directory: *Directory) DirectoryEntry
```

[Source](../../compiler/std/fs/fs.dyn#L91)

```dyn
pub fn close_directory(directory: *Directory) Result
```

[Source](../../compiler/std/fs/fs.dyn#L96)

```dyn
pub fn close(file: *File) Result
```

[Source](../../compiler/std/fs/fs.dyn#L104)

```dyn
pub fn read(file: *File, destination: []u8) Result
```

[Source](../../compiler/std/fs/fs.dyn#L113)

```dyn
pub fn write(file: *File, source: []const u8) Result
```

[Source](../../compiler/std/fs/fs.dyn#L139)

```dyn
pub fn reader(file: *File) stream.Reader
```

[Source](../../compiler/std/fs/fs.dyn#L143)

```dyn
pub fn writer(file: *File) stream.Writer
```

[Source](../../compiler/std/fs/fs.dyn#L148)

Reads one complete file into arena storage, bounded by maximum.

```dyn
pub fn read_all(arena: *memory.Arena, path: []const u8, maximum: usize) ReadAllResult
```

[Source](../../compiler/std/fs/fs.dyn#L178)

```dyn
pub fn write_all(path: []const u8, source: []const u8) Result
```

[Source](../../compiler/std/fs/fs.dyn#L188)

```dyn
pub fn copy_file(source: []const u8, destination: []const u8, scratch: []u8) Result
```

[Source](../../compiler/std/fs/fs.dyn#L221)

origin: 0 start, 1 current, 2 end.

```dyn
pub fn seek(file: *File, offset: isize, origin: usize) OffsetResult
```

[Source](../../compiler/std/fs/fs.dyn#L228)

```dyn
pub fn sync(file: *File) Result
```

[Source](../../compiler/std/fs/fs.dyn#L237)

statx has one fixed layout on supported Linux architectures (Linux 4.11+).
Descriptor lookup avoids path replacement races and does not change file position.

```dyn
pub fn file_metadata(file: *const File) Metadata
```

[Source](../../compiler/std/fs/fs.dyn#L244)

```dyn
pub fn metadata(path: []const u8) Metadata
```

[Source](../../compiler/std/fs/fs.dyn#L254)

```dyn
pub fn remove(path: []const u8) Result
```

[Source](../../compiler/std/fs/fs.dyn#L262)

```dyn
pub fn rename(old_path: []const u8, new_path: []const u8) Result
```

[Source](../../compiler/std/fs/fs.dyn#L271)

```dyn
pub fn make_directory(path: []const u8, mode: usize) Result
```

[Source](../../compiler/std/fs/fs.dyn#L279)

```dyn
pub fn remove_directory(path: []const u8) Result
```

[Source](../../compiler/std/fs/fs.dyn#L287)

```dyn
pub fn symbolic_link(target: []const u8, link: []const u8) Result
```

[Source](../../compiler/std/fs/fs.dyn#L296)

```dyn
pub fn read_link(path: []const u8, destination: []u8) PathResult
```

[Source](../../compiler/std/fs/fs.dyn#L305)

```dyn
pub fn sync_directory(path: []const u8) Result
```

[Source](../../compiler/std/fs/fs.dyn#L314)

```dyn
pub struct AtomicFile {
  file: File,
  destination: []const u8,
  temporary: []const u8,
  active: bool,
}
```

[Source](../../compiler/std/fs/fs.dyn#L320)

```dyn
pub struct AtomicResult { transaction: AtomicFile, error: isize, ok: bool }
```

[Source](../../compiler/std/fs/fs.dyn#L323)

Both paths are borrowed until commit/abort. Temporary must be a sibling chosen by caller.

```dyn
pub fn atomic_begin(destination: []const u8, temporary: []const u8) AtomicResult
```

[Source](../../compiler/std/fs/fs.dyn#L341)

```dyn
pub fn atomic_commit(transaction: *AtomicFile) Result
```

[Source](../../compiler/std/fs/fs.dyn#L354)

Also syncs parent directory, making committed rename durable across power loss on Linux filesystems
which honor fsync for files and directories.

```dyn
pub fn atomic_commit_durable(transaction: *AtomicFile, parent_directory: []const u8) Result
```

[Source](../../compiler/std/fs/fs.dyn#L360)

```dyn
pub fn atomic_abort(transaction: *AtomicFile) Result
```

[Source](../../compiler/std/fs/fs.dyn#L369)

Writes through an explicitly named sibling temporary file and atomically renames it.

```dyn
pub fn write_atomic(destination: []const u8, temporary: []const u8, source: []const u8) Result
```

[Source](../../compiler/std/fs/fs.dyn#L404)

```dyn
pub fn app_directory(kind: AppDirectory, destination: []u8) PathResult
```

[Source](../../compiler/std/fs/fs.dyn#L427)

```dyn
pub fn lock(file: *File, operation: usize) Result
```

[Source](../../compiler/std/fs/fs.dyn#L433)

```dyn
pub fn truncate(path: []const u8, length: usize) Result
```

## Source: compiler/std/fs/remove_tree.dyn

[Source](../../compiler/std/fs/remove_tree.dyn#L3)

Scratch frame storage for iterative, descriptor-relative tree removal.
Names borrow the parent frame's directory buffer, so no paths are rebuilt.

```dyn
pub struct RemovalFrame { directory: Directory, name: []const u8, parent: isize }
```

[Source](../../compiler/std/fs/remove_tree.dyn#L20)

Requires at least 280 scratch bytes per frame. Depth/capacity errors may leave
a partially removed tree. Concurrent mutation may fail; it never follows links.

```dyn
pub fn remove_tree(path: []const u8, frames: []RemovalFrame, scratch: []u8) Result
```
