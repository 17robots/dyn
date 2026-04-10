# Std V1 Design

## Goal

`std` v1 exists to support:

- the Dyn compiler written in Dyn
- basic CLI programs
- explicit allocation
- file/process/path operations
- byte-string handling

It does not try to be complete.

## Out Of Scope For V1

Do not build these yet:

- `std/net`
- `std/thread`
- `std/sync`
- `std/tui`
- `std/hash`
- `std/collections/map`
- `std/collections/string_map`
- `std/collections/interner`
- `std/collections/list`
- `std/collections/heap`
- `std/collections/bst`
- a separate top-level `std/fmt`

## Module Tree

```text
std/
  builtin.dyn
  str.dyn
  mem/
    allocator.dyn
    arena.dyn
    page.dyn
  io/
    writer.dyn
    reader.dyn
  os/
    file.dyn
    fs.dyn
    path.dyn
    process.dyn
  collections/
    vec.dyn
```

Because Dyn groups files by directory+module name, the public module surface stays:

- `use "std/builtin"`
- `use "std/str"`
- `use "std/mem"`
- `use "std/io"`
- `use "std/os"`
- `use "std/collections"`

## Layering

- `builtin` depends on nothing.
- `str` depends on `mem` only for allocating helpers.
- `mem` depends on `builtin` at most.
- `io` depends on `mem` and `str`.
- `os` depends on `io`, `mem`, and `str`.
- `collections` depends on `mem`.

Forbidden in v1:

- `mem` depending on `os`
- `str` depending on `os`
- `collections` depending on `os`
- `os` depending on `collections`

## Module Responsibilities

### `std/builtin`

Purpose:

- compiler-provided target/build metadata only

Public API:

```dyn
pub BuildMode := enum { debug, release_safe, release_fast, release_small }
pub Arch := enum { x86_64, aarch64, riscv64, wasm32 }
pub Os := enum { linux, macos, windows, freestanding }

pub Target := struct {
    mode: BuildMode,
    arch: Arch,
    os: Os,
    sanitize: bool,
}
```

Do not add helpers here.

### `std/mem`

Purpose:

- allocator interface
- allocator implementations
- typed allocation helpers

Files:

- `allocator.dyn`
- `arena.dyn`
- `page.dyn`

Public API:

```dyn
pub Allocator := struct {
    ctx: *any,
    impl_alloc: (ctx: *any, size: usize, align: usize) ?*any,
    impl_free: (ctx: *any, ptr: *any, size: usize),
    impl_realloc: (ctx: *any, ptr: *any, old_size: usize, new_size: usize, align: usize) ?*any,
}

pub Allocator.alloc := (self: Allocator, size: usize, align: usize) ?*any
pub Allocator.free := (self: Allocator, ptr: *any, size: usize)
pub Allocator.realloc := (self: Allocator, ptr: *any, old_size: usize, new_size: usize, align: usize) ?*any
pub Allocator.create := (self: Allocator, T: comp type) ?*T
pub Allocator.destroy := (self: Allocator, T: comp type, ptr: *T)
pub Allocator.create_many := (self: Allocator, T: comp type, n: usize) ?[]T
pub Allocator.destroy_many := (self: Allocator, T: comp type, slice: []T)
pub Allocator.resize_many := (self: Allocator, T: comp type, slice: []T, new_n: usize) ?[]T
```

Arena API:

```dyn
pub Arena := struct { ... }
pub Arena.init := () Arena
pub Arena.allocator := (self: *Arena) Allocator
pub Arena.reset := (self: *Arena)
pub Arena.deinit := (self: *Arena)
```

Page API:

```dyn
pub PageAllocator := struct {}
pub PageAllocator.init := () PageAllocator
pub PageAllocator.allocator := (self: *PageAllocator) Allocator
```

Rules:

- `Allocator` is the ownership boundary type.
- Keep debug tracking and fancy allocator diagnostics out of v1 unless the compiler needs them.
- Do not add GPA or fixed allocators in the first pass unless a concrete caller needs them.

### `std/str`

Purpose:

- byte-string operations on `[]u8`
- numeric parsing/formatting helpers used by `io` and compiler code

Public API:

```dyn
pub SplitResult := struct {
    left: []u8,
    right: []u8,
}

pub eq := (a: []u8, b: []u8) bool
pub starts_with := (s: []u8, prefix: []u8) bool
pub ends_with := (s: []u8, suffix: []u8) bool
pub contains := (s: []u8, needle: []u8) bool
pub find := (s: []u8, needle: []u8) ?usize
pub find_byte := (s: []u8, b: u8) ?usize
pub rfind := (s: []u8, needle: []u8) ?usize
pub rfind_byte := (s: []u8, b: u8) ?usize
pub is_empty := (s: []u8) bool
pub is_whitespace := (b: u8) bool
pub trim_start := (s: []u8) []u8
pub trim_end := (s: []u8) []u8
pub trim := (s: []u8) []u8
pub split_once := (s: []u8, delim: u8) ?SplitResult

pub parse_uint := (s: []u8) ?u64
pub parse_int := (s: []u8) ?i64
pub parse_hex_uint := (s: []u8) ?u64
pub parse_float := (s: []u8) ?f64

pub uint_to_buf := (n: u64, buf: []u8) []u8
pub int_to_buf := (n: i64, buf: []u8) []u8
pub uint_to_hex_buf := (n: u64, buf: []u8) []u8

pub split := (s: []u8, delim: u8, alloc: Allocator) ?[][]u8
pub repeat := (s: []u8, n: usize, alloc: Allocator) ?[]u8
```

Rules:

- `str` means UTF-8 bytes, not a separate string object.
- No regex, unicode segmentation, or rope/string-builder APIs in v1.
- Mutating ASCII case helpers are optional and can wait.

### `std/io`

Purpose:

- generic stream interfaces
- minimal printing support

Files:

- `writer.dyn`
- `reader.dyn`

Do not build `buf`, `buf_reader`, or `fmt` in the first pass unless needed.

Public API:

```dyn
pub Writer := struct {
    ctx: *any,
    write_fn: (ctx: *any, buf: []u8) usize,
}

pub Writer.write_all := (self: Writer, buf: []u8) usize
pub Writer.write_byte := (self: Writer, byte: u8) usize
pub Writer.print := (self: Writer, v: any)
pub Writer.println := (self: Writer, v: any)
```

```dyn
pub Reader := struct {
    ctx: *any,
    read_fn: (ctx: *any, buf: []u8) usize,
}

pub Reader.read_byte := (self: Reader) ?u8
pub Reader.read_exact := (self: Reader, buf: []u8) bool
pub Reader.read_all := (self: Reader, alloc: Allocator) ?[]u8
```

Rules:

- `Writer.print` is enough for v1 formatting.
- If placeholder formatting is needed later, add `io.fprint` as a thin helper inside `std/io`, not a separate top-level module.
- `print(any)` only needs to support the types the compiler CLI actually prints now:
  - `[]u8`
  - integers
  - floats
  - bool

### `std/os`

Purpose:

- concrete OS functionality used by CLI and compiler tooling

Files:

- `file.dyn`
- `fs.dyn`
- `path.dyn`
- `process.dyn`

#### `std/os/file`

Purpose:

- file handle wrapper
- stdio handles
- bridge from OS handles to `io.Reader` / `io.Writer`

Public API:

```dyn
pub File := struct {
    fd: i32,
}

pub File.writer := (self: File) io.Writer
pub File.reader := (self: File) io.Reader
pub File.close := (self: File)

pub stdout := File.{ fd: 1 }
pub stderr := File.{ fd: 2 }
pub stdin := File.{ fd: 0 }

pub print := (v: any)
pub println := (v: any)
pub eprint := (v: any)
pub eprintln := (v: any)
pub printf := (fmt: []u8, args: any)
pub eprintf := (fmt: []u8, args: any)
```

Note:

- `printf`/`eprintf` are convenience APIs. If placeholder formatting is deferred, these can temporarily be omitted and the compiler code adjusted to `print`/`println`.

#### `std/os/fs`

Purpose:

- file reads/writes and simple filesystem operations

Public API:

```dyn
pub read_file := (path: []u8, alloc: Allocator) ?[]u8
pub write_file := (path: []u8, data: []u8, alloc: Allocator) bool
pub exists := (path: []u8, alloc: Allocator) bool
pub rename := (old: []u8, new_: []u8, alloc: Allocator) bool

pub FileStat := struct {
    size: usize,
    mode: u32,
    kind: u32,
}
pub stat := (path: []u8, alloc: Allocator) ?FileStat
```

Keep raw open/close/lseek wrappers only if some real caller needs them.

#### `std/os/path`

Purpose:

- pure byte-path manipulation

Public API:

```dyn
pub is_absolute := (path: []u8) bool
pub dirname := (path: []u8) []u8
pub basename := (path: []u8) []u8
pub extension := (path: []u8) []u8
pub strip_extension := (path: []u8) []u8
pub join := (base: []u8, part: []u8, alloc: Allocator) ?[]u8
```

#### `std/os/process`

Purpose:

- process exit, argv, env

Public API:

```dyn
pub exit := (code: i32)
pub args := (alloc: Allocator) ?[][]u8
pub getenv := extern (name: *any) ?*any = "getenv"
pub getenv_str := (name: []u8, alloc: Allocator) ?[]u8
```

Do not build subprocess spawn for v1 unless there is a concrete use.

### `std/collections`

Purpose:

- only one container in v1: `Vec`

Files:

- `vec.dyn`

Public API:

```dyn
pub Vec := (T: comp type) type {
    init := (alloc: Allocator) Self
    deinit := (self: *Self)
    push := (self: *Self, item: T) bool
    pop := (self: *Self) ?T
    get := (self: Self, i: usize) ?*T
    clear := (self: *Self)
    clone := (self: Self, alloc: Allocator) ?Self
}
```

Rules:

- `Vec` is enough to get the compiler code moving.
- Do not add `Map` until there is a real caller that needs key lookup.

## Aggregate Module Policy

The compiler Dyn code currently imports:

- `use "std/mem"`
- `use "std/os"`
- `use "std/collections"`
- `use "std/str"`

So v1 should preserve those aggregate module names.

That means:

- `std/mem/*.dyn` all declare `module mem`
- `std/os/*.dyn` all declare `module os`
- `std/collections/*.dyn` all declare `module collections`
- `std/io/*.dyn` all declare `module io`

## Naming Policy

- Use nouns for types: `Allocator`, `Arena`, `File`, `Writer`, `Reader`, `Vec`
- Use verbs for free functions: `read_file`, `write_file`, `join`, `trim`
- Prefer methods when the operation is naturally on a value:
  - `writer.write_all(...)`
  - `vec.push(...)`
  - `arena.allocator()`

## Implementation Order

1. `std/builtin`
2. `std/mem/allocator`
3. `std/mem/arena`
4. `std/io/writer`
5. `std/io/reader`
6. `std/str`
7. `std/os/file`
8. `std/os/process`
9. `std/os/fs`
10. `std/os/path`
11. `std/collections/vec`

## Acceptance Criteria For V1

`std` v1 is done when:

- `compiler-dyn/main.dyn` builds against it with only:
  - `std/mem`
  - `std/os`
  - `std/str`
  - `std/collections`
- no deferred module is required by the Dyn compiler code
- each kept module has a single clear responsibility
- there are no old-syntax leftovers in the rebuilt files
