# Idiomatic Dyn

This is the practical reference for writing clear, correct Dyn. For exact language rules, see
the [language reference](language.md); for the standard library, see [std](std.md); for layout and naming, see [style](style.md).

## The basic shape

A directory is one module. All immediate `.dyn` files share a namespace. Put the executable entry
point in `main.dyn`; it must be exactly `fn main()` (optionally `pub`). Import other modules with
`use`, and qualify imported declarations. Import aliases are shared by all files in the
module. Repeating an alias for the same module in another file is accepted and
internally deduplicated; different aliases may also refer to the same module.
An alias cannot refer to different modules. Duplicate aliases within one file are
errors; importing the same module under multiple aliases within one file is a
`dyn vet` finding.

```dyn
use "std/io"

fn greeting(name: []const u8) {
  io.println("hello, {}", name)
}

fn main() {
  greeting("Dyn")
}
```

Prefer inferred locals when the type is obvious. Write the type when it documents an important
boundary, controls integer width, or declares zero-initialized storage.

```dyn
count := 3                 // inferred
offset: isize = 0         // explicit representation
buffer: [4096]u8          // fixed stack storage, zero-filled
```

Names never shadow: a local cannot reuse the name of anything still in scope, in the same block or
a nested one, nor the name of a global, function or module. Pick a new name
(`parsed := parse(text)`) or reassign the existing variable. A name is free again once its block
or loop ends. Use
`const` for compile-time constants and `distinct type` for values that must not mix by accident.

```dyn
const BufferCapacity: usize = 4096
distinct type UserId = u32
```

Fixed-array lengths accept integer constants and simple nonnegative constant
arithmetic: `[BufferCapacity]u8` or, after importing `std/mem`, `[4 * mem.KiB]u8`.
They do not accept runtime lengths. See the tested
[memory patterns](memory-patterns.md) for complete examples.

## Choose storage from the lifetime

Dyn does not hide allocation. Start by deciding how long the value must live.

- Small, fixed, local value: ordinary local or fixed array.
- Output whose maximum size is known: caller-provided slice.
- Many values sharing one lifetime: arena.
- Temporary work inside a function: mark and rewind a scratch arena.
- Per-frame or per-request data: reset a dedicated arena after each iteration.
- Foreign or OS resource: use its explicit acquire/release pair.

```dyn
use "std/mem"

fn do_work(scratch: *mem.Arena) {
  mark := mem.arena_mark(scratch)
  defer { mem.arena_rewind(scratch, mark) }

  bytes := mem.push_bytes(scratch, 1024)
  _ = bytes
  // bytes becomes invalid when this function rewinds scratch.
}

fn main() {
  root := mem.arena_alloc(mem.MiB)
  defer mem.arena_release(root)
  do_work(root)
}
```

An arena is a `*mem.Arena`, with its header in its first backing block. Create it
explicitly: `mem.arena_alloc(0)` chooses the target's default block size. Owned
arenas add blocks when needed without moving earlier allocations. For a backing
budget, use `mem.arena_from_source(mem.pages(limit))`; the limit includes every
block's header. Pushes succeed or panic, like an index out of range.

A nil owner pointer is inactive, not a lazily allocating arena. Pass the pointer
directly. Never copy or reconstruct a live header through `arena.*`; pointer
handles do not enforce uncopiability. Reset invalidates all allocations and frees
later blocks, retaining the first block. Rewind invalidates later allocations and
frees blocks added after the mark. Release invalidates the arena pointer too:
release an owner once, then discard or nil the pointer. Releasing nil is safe.

Caller-buffer arenas never grow. The aligned header consumes `mem.ArenaHeader`
bytes plus up to 15 initial alignment bytes, so provide payload size plus
`mem.ArenaBufferOverhead` bytes to guarantee that payload capacity. A smaller
buffer that cannot hold the header panics. After releasing a buffer arena,
initialize its backing with `arena_from_buffer` again before reuse.

For long-running programs, partition one root arena by lifetime:

```dyn
root := mem.arena_alloc(mem.MiB)
defer mem.arena_release(root)
permanent := mem.arena_from_source(mem.within(root, 512 * mem.KiB))
frame := mem.arena_from_source(mem.within(root, 256 * mem.KiB))
scratch := mem.arena_from_source(mem.within(root, 256 * mem.KiB))
```

Store application state in `permanent`, reset `frame` once per loop/request, and rewind `scratch`
inside temporary operations. Each child takes its blocks from the parent as it
grows, and each child limit includes its blocks' headers. A result returned from a scratch operation must be copied
into storage that lives long enough.

`mem.KiB`, `mem.MiB`, and `mem.GiB` express binary byte units, not recommended
budgets. The capacities above are illustrative. Name application limits and measure
use with `mem.arena_used` before selecting budgets. For an input-dependent array count, use
`mem.push_array(Item, arena, count)`: it checks the size multiplication and returns
zeroed `[]Item`.

## Slices, strings, arrays, and pointers

A string is immutable UTF-8 bytes: `[]const u8`. It is length-based, not zero-terminated. Slices and
pointers borrow storage; they do not own it.

```dyn
storage: [64]u8
whole := storage[..]
prefix := whole[..8]
length := prefix.len
```

Use arrays for fixed-size owned values and slices for views or API boundaries. Prefer slices over a
pointer plus a separate count. Bounds are checked.

Use `*T` only when you need identity, mutation through a reference, an optional value (`nil`), or an
FFI boundary. Use `*const T` for read-only borrowing. `rawptr` is only for untyped OS/foreign memory;
cast it to a typed pointer before access.

```dyn
fn increment(value: *i32) {
  value.* += 1
}

fn main() {
  value: i32 = 4
  increment(&value)
}
```

Do not retain a pointer or slice after its stack frame, arena mark, reset, or mapping has ended. Dyn
checks bounds, nil, and alignment, but it does not prove lifetimes.

## Functions and conversions

Pass small values and descriptors by value. Pass large mutable state by pointer. Use a const pointer
when a function only observes a struct.

```dyn
fn lookup(app: *const App, id: UserId) *const User {
  // Return nil when absence is ordinary.
  return nil
}
```

Implicit numeric conversion happens only when every source value is exactly representable. Thus
`u32 -> usize` and `i32 -> isize` are valid on a 64-bit target, while `i32 -> usize`, narrowing, and
distinct-type conversion require `#cast`.

Use native variadics through their named slice:

```dyn
fn sum(values: ...usize) usize {
  total: usize = 0
  for value in values { total += value }
  return total
}
```

Use `...any` only when heterogeneous values are genuinely useful. Values in an `any` pack are
borrowed; inspect them with an exhaustive type `case` and do not retain them.

## Errors and cleanup

A function that can fail returns `T!E`: its value, or an error `E`. `E` is
an enum, or a union of enums (`FsErr | ParseErr`) when a function can fail in
more than one module's way. `try` passes a failure up, running `defer` and
`errdefer` on the way; `catch` handles it where the program knows what to do.
`std/io`, `std/fs` and `std/process` fail with `io.IoErr`, and printing one
gives its meaning ("not found"). The error does not carry the path, so the
code that catches it names what it was working on:

```dyn
fn copy(arena: *mem.Arena, path: []const u8, copy_path: []const u8) !io.IoErr {
  text := try fs.read_all(arena, path, 1 << 20)
  try fs.write_all(copy_path, text)
}
```

```dyn
copy(arena, path, copy_path) catch err {
  io.eprintln("tool: copy {}: {}", path, err)
  return 1
}
```

React to one kind with `case`: `.NotFound => { ... }`, `_ => { fail err }`.
Iterators return their value and set `ended` on their state at the end;
the end of the input is not a failure. Cleanup cannot fail (`fs.close`,
`mem.arena_release`), so it works in a `defer` after any failure.

### Modules that still take a status

The rest of std and the vendor packages are moving to `T!E`. Until then they
take a `*fail.Status`, the way a function that allocates takes a
`*mem.Arena`. The first failure is recorded in the status and stays there;
every later call given that status does nothing and returns zero or empty.
Code does not check after each call: it checks `status.failed` once, before it
acts on the results, and prints `status.failure` with `fail.describe`.

Three rules cover every such call:

1. **If it can fail, it takes `&status`.** Its result is the value itself,
   zero or empty after a failure.
2. **A lookup always returns a usable value.** When it is not there the value
   is zero or empty and the status records `NotFound`; when it is there but
   wrong, `InvalidInput`. Read an optional value with a status of its own, so
   a missing one stops nothing else, or pass `nil` when you do not care why:

   ```dyn
   status: fail.Status
   port := json.get<i64>(&status, root, "port")   // required
   debug := json.get<bool>(nil, root, "debug")    // false when missing
   ```

   `nil` works for every std and vendor call that takes a status: the call
   does its work, records nothing, and returns zero or empty if it fails.
   Inside, it still sees its own failures, so a reader given `nil` still
   ends and a writer that runs out of room stops.

   Iterators return their value too. The end of the input is not a failure,
   so it does not go on the status: the call sets `ended` on the state you
   passed (`scan.ended`, `reader.ended`) and returns zero.
3. **Check `status.failed` before you use what you got:** before printing
   results, reporting success, or using a computed number as a size or index.

In a loop that keeps going after a failure (a server, a command loop, each of
many files), give each item its own status. Cleanup uses functions that take
no status (`fs.close`, `*_free_owned`, `*_destroy`), so it works after a
failure. To react to one kind of failure, such as falling back when a file is
missing, give that step its own status and look at `status.failure.kind`. An
empty result is not a failure test; `status.failed` is, and `dyn vet` warns
about a status that is never read, one given a new value before it is read, and
an empty result used as the test.
A failure keeps its own copy of its text; read the parts with
`fail.operation_text`, `fail.path_text` and `fail.message_text`.

### Writing a library

The same three rules, from the other side:

1. **Take `status`, return the value.** No result struct, no error type of
   your own: return zero or empty after a failure.
2. **Pass the same status to everything you call.** A failure from `fs` or
   `json` reaches your caller with its own operation, path and reason; there is
   nothing to translate. Record your own failures one of three ways:
   `fail.invalid(status, "config", path, "port out of range")` for bad input,
   `fail.at(status, fail.Kind.InvalidInput, "read config", "expected '='",
   offset)` for a place in the input, and `fail.set(status, fail.make(kind,
   operation, path, message))` for anything else. Native codes become
   failures with `io.from_linux` and its siblings.
3. **Guard with `if status.failed { return }` only before work that does not
   take the status:** raw system calls, writes into caller memory, loops that
   only end on data. A function made only of status-taking calls needs no
   check at all.

```dyn
pub fn load(arena: *mem.Arena, status: *fail.Status, text: []const u8, path: []const u8) Config {
  doc := json.parse(arena, status, text)
  port := json.get(i64, status, doc, "port")
  if port > 65535 {
    fail.invalid(status, "config", path, "port out of range")
  }
  return Config{ port: port }
}
```

Other outcomes are values, not failures:

- **Absence in memory you own:** `map.get` returns `nil`, tree navigation
  returns an empty stub, and every byte `find*` returns `text.len` on a
  miss. Lookups into input (JSON, INI, HTTP, the environment) record
  `NotFound` instead (rule 2).
- **The end of an iterator** is `ended` on its state, set by the call that
  found nothing left. A step with several normal outcomes says so in an
  enum, such as `Want.Read`/`Want.Write` for a nonblocking socket.
- **Yes-or-no questions** return `bool`: `is_*`, `has_*`, `valid`, `verify`,
  `try_lock`.
- **Math does not fail:** degenerate input (a singular matrix, a zero axis)
  gives the zero value.
- **A broken invariant** is `#panic`. There is no recovery.

A scanner takes the status like any other call, so a loop over it reads
straight through and checks once at the end. A failure also sets `ended`, so
the loop stops either way:

```dyn
status: fail.Status
scan := ini.scanner(text)
for {
  item := ini.next(&status, &scan)
  if scan.ended {
    break
  }
  apply(item)
}
if status.failed {
  report(status.failure)
}
```

`pop` on `std/container/array` and `std/container/ring` returns the zero value
when empty; check the count first where empty is possible.

Ownership is independent of success: say whether a returned slice borrows the
input, occupies caller storage or lives in a supplied arena, and never allocate
on failure.

Use `defer` immediately after acquiring a resource. Defers run in LIFO order on normal scope exit
and control transfer; a panic does not run them.

```dyn
resource := acquire()
if resource == nil { return false }
defer { release(resource) }
```

## Control flow and data modeling

Prefer early returns for invalid input and failure. Use `case` when modeling a closed set; every case
must be exhaustive. Use a kind enum beside a struct when the alternatives carry different data.

```dyn
enum State { Pending, Complete(usize) }

fn describe(state: State) []const u8 {
  case state {
    State.Pending => { return "pending" }
    State.Complete(_) => { return "complete" }
  }
}
```

Use `for item in values` when copying each element is fine. Use `for *item` when mutating array/slice
elements in place. Use `for item, i in values` (or `for *item, i`) when the body needs the element
and its `usize` index. Use `for i in 0..count` for index loops instead of a manual counter; use `..=`
when the last value is included. Use `for i in #reverse(0..count)` or `for value in
#reverse(values)` to walk backwards instead of a manual down-counter. Use condition-form `for condition` or bare `for {}` for state
machines and event loops. Loop and block names are reusable once their scope ends, so consecutive
loops can all use `i` or `value`.

Use structs for related state and distinct unsigned integer types for bit masks. Enums represent one
choice, not an arbitrary collection of flags.

## Text and I/O

`std/io` owns the small `Reader`/`Writer` seam, standard streams, and formatted output.
`std/fmt` remains useful when text must first be constructed in caller-owned
storage. None of these require printing to be a compiler builtin or allocate implicitly.

```dyn
use "std/io"

io.println("count: {}", count)
try io.println_to(log_file, "count: {}", count)
```

`io.print` and `io.println` write to standard output and `io.eprint` and `io.eprintln` to standard
error; they ignore write failures such as a closed pipe. `io.print_to` and `io.println_to` take any
writer and return `!io.IoErr`. All of them support `{}` substitutions and `{{`/`}}` literal braces.
`std/terminal` provides terminal controls.

A `Reader` or `Writer` is a data pointer and one function that returns `usize!io.IoErr`. `io.read`
returns the count read, 0 at the end of the stream:

```dyn
for {
  count := try io.read(reader, chunk[..])
  if count == 0 { break }
  use_bytes(chunk[..count])
}
```

`io.write` writes everything, `io.read_exact` fills its buffer or fails if the stream ends partway,
and `io.copy` copies a reader to a writer.
Treat partial operations and native errors as ordinary results. Do not assume text is C-compatible;
use `std/c` helpers at explicit FFI boundaries.

## C interoperability

Keep foreign declarations narrow and wrap them with a Dyn-shaped API. State ownership in the wrapper.

```dyn
extern fn native_read "read"(descriptor: i32, data: rawptr, count: usize) isize
```

Pass explicit `--link` inputs. C variadics are only for foreign ABI declarations and accept the C-safe
promoted types. Do not expose Dyn slices, strings, or `any` as if they were C values.

## Practical rules

- Make ownership and lifetime visible in parameter names and documentation.
- Let callers provide buffers or arenas; do not allocate secretly.
- Group allocations by lifetime instead of freeing objects individually.
- Keep scratch results inside the scratch lifetime.
- Prefer `[]const u8` and `*const T` when mutation is unnecessary.
- Use lossless implicit conversions; make lossy intent visible with `#cast`.
- Check expected failures; panic only when continuing would violate an invariant.
- Make zero a useful empty or inactive value; initialize arena pointers before allocation.
- Keep imported names qualified and publish only the module's intended API.
- Use `_ = function()` when intentionally discarding a non-void result.
- Compile with `dyn check DIR`; test debug and release builds.

## Check errors once

When several steps can fail, `try` each one and handle the failure once, where the program knows
what to do with it.

```dyn
use "std/fs"
use "std/io"

fn save(path: []const u8) !io.IoErr {
  file := try fs.create(path)
  defer fs.close(&file)
  try fs.write(&file, "name: ")
  try fs.write(&file, "dyn\n")
}
```

The code stays straight, a failure stops the remaining work, and the `defer` still closes the
file.
