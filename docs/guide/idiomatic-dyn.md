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

  bytes := mem.push_bytes_uninit(scratch, 1024)
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
budget, use `mem.arena_alloc_bounded(block_size, limit)`; the limit includes every
block's header. Ordinary pushes succeed or panic; `arena_try_push` reports
exhaustion when caller code needs a recoverable result.

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
permanent := mem.arena_sub(root, 512 * mem.KiB)
frame := mem.arena_sub(root, 256 * mem.KiB)
scratch := mem.arena_sub(root, 256 * mem.KiB)
```

Store application state in `permanent`, reset `frame` once per loop/request, and rewind `scratch`
inside temporary operations. Each child capacity includes its own header, and the
parent also reserves a header. These three child regions can therefore require a
second parent block. A result returned from a scratch operation must be copied
into storage that lives long enough.

`mem.KiB`, `mem.MiB`, and `mem.GiB` express binary byte units, not recommended
budgets. The capacities above are illustrative. Name application limits and measure
peak usage before selecting budgets. For an input-dependent array count, use
`mem.push_array(Item, arena, count)`: it checks the size multiplication and returns
zeroed `[]Item`.

## Slices, strings, arrays, and pointers

A string is immutable UTF-8 bytes: `[]const u8`. It is length-based, not zero-terminated. Slices and
pointers borrow storage; they do not own it.

```dyn
storage: [64]u8
whole := storage[..]
prefix := whole[..8]
length := #len(prefix)
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

A function that can fail takes a `*fail.Status`, the way a function that
allocates takes a `*mem.Arena`, so its signature says it can fail. The first
failure is recorded in the status and stays there; every later call given that
status does nothing and returns zero or empty. Code does not check after each
call: it checks `status.failed` once, before it acts on the results, and prints
`status.failure` with `fail.describe`, such as
`open app.json: no such file or directory`.

```dyn
status: fail.Status
text := fs.read_all(arena, &status, path, 1 << 20)   // fails: empty
fs.write_all(&status, copy_path, text)               // already failed: writes nothing
if status.failed {
  storage: [512]u8
  io.eprintln("tool: {}", fail.describe(storage[..], status.failure))
  return 1
}
```

Five rules make it work:

1. **One status per unit of work.** A failed status stays failed. Work that
   must carry on after a failure, such as a command loop, a server or each of
   many files, declares a status per item, inside the loop.
2. **Check before you act:** before printing results, reporting success, or
   doing anything that does not take the status, such as your own side
   effects, using a computed number as a size or index, or a loop that only
   ends on data.
3. **Cleanup after a failure** uses a fresh status, or functions that take
   none such as `fs.close`: the failed status turns cleanup into no-ops too.
4. **An empty result is not a failure test.** An empty file gives empty text;
   `status.failed` is the test.
5. **To react to one kind of failure,** such as falling back when a file is
   missing, give that step its own status and look at `status.failure.kind`.
   To pass it on, `fail.set(status, step.failure)`.

Your own code records a problem it finds in its input the same way, with
`fail.invalid(status, "config", path, "port out of range")`. A failure borrows
its `path` and `message` text, so that text must outlive the check.

Modules move to this model one at a time; `std/fs` is first. A module that has
not moved yet returns `{value, failure}` (`io.Result(T)`, `parse.Result(T)`):
check it with `io.failed(result.failure)` or `parse.failed(result.failure)`.

- **Absence is not failure:** a lookup returns `nil` (`map.get`) or an empty
  stub for tree nodes, and every `find*` returns `#len(text)` on a miss.
- **A step with several normal outcomes** returns a `Status` enum such as
  `Complete`/`End` or `Event`/`Empty`. A status never has an `Error`
  variant; the failure is its own field next to it.
- **Yes-or-no questions** return `bool`, and only predicates do:
  `is_*`, `has_*`, `valid`.
- **A broken invariant** is `#panic`. There is no recovery.

```dyn
enum ParseStatus { Empty, Invalid, Complete }
struct ParseResult { value: u64, offset: usize, status: ParseStatus }
```

A parser, writer or builder keeps its first error in its own state, as Go's
`bufio.Scanner.Err()` does. The caller loops, then checks once:

```dyn
scan := ini.scanner(text)
for {
  item := ini.next(&scan)
  if !item.found {
    break
  }
  apply(item.value)
}
if parse.failed(scan.failure) {
  report(scan.failure)
}
```

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
enum State { Pending, Complete: usize }

fn describe(state: State) []const u8 {
  case state {
    State.Pending => { return "pending" }
    State.Complete _ => { return "complete" }
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
use "std/io" io

io.println("count: {}", count)
result := io.println_to(log_file, "count: {}", count)
if io.failed(result.failure) { #panic("log write failed") }
```

`io.print` and `io.println` write to standard output and return nothing, so a terminal print needs
no `_ =`; `io.eprint` and `io.eprintln` write to standard error. They ignore write failures such
as a closed pipe. `io.print_to` and `io.println_to` take any writer and return the `Transfer`, so
a discarded result there stays visible as `_ =`. All of them support `{}` substitutions and
`{{`/`}}` literal braces. `std/terminal` provides terminal controls.
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

When several steps can fail, pass one status through them and check it at the end. Each step does
nothing once a failure is recorded, and the failure names the operation and the path.

```dyn
use "std/fail"
use "std/fs"

fn save(status: *fail.Status, path: []const u8) {
  file := fs.create(status, path)
  defer fs.close(&file)
  fs.write(status, &file, "name: ")
  fs.write(status, &file, "dyn\n")
}
```

A function of your own that can fail takes the status the same way, and does not need to check it
unless it is about to act on a result.

The code stays straight, a failure stops the remaining work, and there is one `if` at the end.
