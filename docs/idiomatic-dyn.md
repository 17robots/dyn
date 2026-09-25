# Idiomatic Dyn

This is the practical reference for writing clear, correct Dyn. For exact language rules, see
[`language.md`](language.md); for package APIs, see [`packages.md`](packages.md).

## The basic shape

A directory is one module. All immediate `.dyn` files share a namespace. Put the executable entry
point in `main.dyn`; it must be exactly `fn main()` (optionally `pub`). Import other modules with
`use`, and qualify imported declarations.

```dyn
use "std/io"
use "std/terminal"

fn greeting(name: []const u8) {
  _ = io.println(terminal.stdout(), "hello, {}", name)
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

  bytes := mem.arena_push(scratch, 1024, 1)[..1024]
  _ = bytes
  // bytes becomes invalid when this function rewinds scratch.
}

fn main() {
  root := mem.arena_create(1024 * 1024)
  if !root.ok { #panic("arena backing unavailable") }
  defer _ = mem.arena_release(&root.arena)
  do_work(&root.arena)
}
```

Use `arena_try_push` when exhaustion is an expected outcome. Use `arena_push` when capacity was
established by program design and exhaustion is an invariant failure. Never copy an arena after it
has begun allocating. Reset, rewind, or release invalidates every affected pointer and slice.

For long-running programs, partition one root arena by lifetime:

```dyn
root := mem.arena_create(1024 * 1024)
if !root.ok { #panic("arena backing unavailable") }
defer _ = mem.arena_release(&root.arena)
permanent := mem.arena_sub(&root.arena, 512 * 1024)
frame := mem.arena_sub(&root.arena, 256 * 1024)
scratch := mem.arena_sub(&root.arena, 256 * 1024)
```

Store application state in `permanent`, reset `frame` once per loop/request, and rewind `scratch`
inside temporary operations. A result returned from a scratch operation must be copied into storage
that lives long enough.

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
fn increment(value: *i32) { value.* += 1 }

value: i32 = 4
increment(&value)
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
    State.Pending => { return "pending" },
    State.Complete _ => { return "complete" },
  }
}
```

Use `for item in values` when copying each element is fine. Use `for *item` when mutating array/slice
elements in place. Use condition-form `for condition` or bare `for {}` for state machines and event
loops.

Use structs for related state and distinct unsigned integer types for bit masks. Enums represent one
choice, not an arbitrary collection of flags.

## Text and I/O

`std/io` owns the small `Reader`/`Writer` seam and formatted output. `std/terminal` supplies stdout
and stderr writers. `std/fmt` remains useful when text must first be constructed in caller-owned
storage. None of these require printing to be a compiler builtin or allocate implicitly.

```dyn
use "std/io" io
use "std/terminal" terminal

result := io.println(terminal.stdout(), "count: {}", count)
if result.status == io.Status.Error { #panic("stdout write failed") }
```

`io.print` supports `{}` substitutions and `{{`/`}}` literal braces. Terminal does not duplicate
the printing API: pass `terminal.stdout()` or `terminal.stderr()` to `io.print` or `io.println`.
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
- Keep imported names qualified and publish only the module's intended API.
- Use `_ = function()` when intentionally discarding a non-void result.
- Compile with `dyn check DIR`; test debug and release builds.

For a complete interactive example using permanent, frame, and alternating scratch arenas, see
[`projects/field-notes`](../projects/field-notes/README.md).
