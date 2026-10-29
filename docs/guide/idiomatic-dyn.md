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
  _ = io.println(io.stdout(), "hello, {}", name)
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
buffer: [4096]u8 = []     // fixed stack storage, zero-filled
```

Shadowing is forbidden. Reassign an existing variable instead of introducing another with the same
name. Use `const` for compile-time constants and `distinct type` for values that must not mix by
accident.

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
  root := mem.arena_create(mem.MiB)
  defer mem.arena_release(root)
  do_work(root)
}
```

An arena is a `*mem.Arena`, with its header in its first backing block. Create it
explicitly: `mem.arena_create(0)` chooses the target's default block size. Owned
arenas add blocks when needed without moving earlier allocations. For a backing
budget, use `mem.arena_create_bounded(block_size, limit)`; the limit includes every
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
root := mem.arena_create(mem.MiB)
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
storage: [64]u8 = []
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

Dyn has no mandatory universal result type. Return the smallest ordinary value that preserves what
the caller needs:

- `bool` for success/failure with no useful detail.
- `nil` or another unambiguous sentinel for lookup-style absence.
- A struct for a value plus status, count, offset, or OS error.
- An enum when callers must distinguish several outcomes.
- `#panic` only for broken invariants or explicitly infallible convenience APIs.

```dyn
enum ParseStatus { Empty, Invalid, Complete }
struct ParseResult { value: u64, offset: usize, status: ParseStatus }
```

Code that does many fallible steps in a row, such as a parser, a writer or a builder, keeps
its first error in its own state and turns later calls into no-ops. The caller loops, then
checks once, as with Go's `bufio.Scanner.Err()`:

```dyn
scan := ini.scanner(text)
for {
  item := ini.next(&scan)
  if !item.ok {
    break
  }
  apply(item.entry)
}
if scan.error != ini.ErrorKind.None {
  report(scan.error_line)
}
```

OS operations return `{value, ok, kind, error}`, because partial counts and native error
numbers matter. Ownership is independent of success: say whether a returned slice borrows the
input, occupies caller storage or lives in a supplied arena, and never allocate on failure.

Handle expected failures near the operation. Use `defer` immediately after successful resource
acquisition. Defers run in LIFO order on normal scope exit, control transfer, and panic.

```dyn
resource := acquire()
if resource == nil { return false }
defer { release(resource) }
```

## Control flow and data modeling

Prefer early returns for invalid input and failure. Use `case` when modeling a closed set; every case
must be exhaustive. Use payload enums when the alternatives carry different data.

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
elements in place. Use `for i in 0..count` for index loops instead of a manual counter; use `..=`
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

result := io.println(io.stdout(), "count: {}", count)
if result.status == io.Status.Error { #panic("stdout write failed") }
```

`io.print` supports `{}` substitutions and `{{`/`}}` literal braces. Pass `io.stdout()`
or `io.stderr()` to `io.print` or `io.println`. `std/terminal` provides terminal controls.
Treat partial operations and native errors as ordinary results. Do not assume text is C-compatible;
use `std/c` helpers at explicit FFI boundaries.

## C interoperability

Keep foreign declarations narrow and wrap them with a Dyn-shaped API. State ownership in the wrapper.

```dyn
extern fn native_read "read"(descriptor: i32, data: rawptr, count: usize) isize
```

Pass explicit `--link` inputs. C variadics are only for foreign ABI declarations and accept the C-safe
promoted types. Do not expose Dyn slices, strings, `any`, or payload enums as if they were C values.

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
