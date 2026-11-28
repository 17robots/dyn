# Dyn language reference

This page defines the language as the compiler implements it. For how to write
Dyn well, read [idiomatic Dyn](idiomatic-dyn.md) first.

## Modules and entry points

A directory is one module; its immediate `.dyn` files share one namespace. Files are
sorted canonically for deterministic processing. `dyn build DIR` requires `DIR/main.dyn`
containing `fn main()` (optional `pub`). `fn main() i32` returns the process exit code; plain
`fn main()` exits 0. `main` takes no parameters, so nothing runs before its first line; for the
arguments and an arena that lives for the whole program, call `process.start()` yourself.
`dyn check` also accepts library modules.

```dyn
use "std/io"
use "std/process"

fn main() i32 {
  program := process.start()
  name: []const u8 = "world"
  if program.args.len > 1 {
    name = program.args[1]
  }
  io.println("hello {}", name)
  return 0
}
```

Compiler resource contract currently limits one source file to 64 MiB, one module to 4096 source
files, one merged module to 256 MiB, and syntax nesting to 1024 levels. Exceeding a limit is a diagnostic, not an allocation
failure or compiler crash.

`use "std/terminal"` binds `terminal`; `use raw_io "std/io"` binds `raw_io`; `use io "std/io",
files "std/fs", "std/mem"` imports several modules in one `use`. An alias always comes before its
path; `as` is invalid. Relative
imports use `./` or `../` but cannot escape project root. Other paths resolve from project
root; `std/` and `vendor/` resolve only inside the SDK. Third-party libraries
are copied into the project (see [style](style.md#third-party-code)) and must use
relative paths for their own modules. `DYN_SDK` may name an SDK root containing
`std/` and `vendor/` collections, which is useful for SDK development and alternate installations.
Import paths are canonicalized. Declarations across
same module see each other regardless of file/source order. `pub` controls imported access.
Imported functions and types must currently be module-qualified; imports never inject names into
the local namespace. Qualified enum construction and patterns use `module.Enum.Variant`, or the
`.Variant` shorthand where one enum type is expected (see [enums](#values-and-types)).

Top-level variable syntax also declares globals. Globals are zero-initialized before optional
runtime initialization and may be mutated; imported globals require `pub` and qualified access.
Constants require compile-time expressions and cannot be assigned after declaration. An inferred
constant built only from literals and other such constants, `const LIMIT := 64` or
`const MASK := 1 << 12`, adapts to each use like a literal: it fits a `u8`, a `u64` or an `f64`
where one is expected, a value that does not fit is an error at that use, and with no expected
type it is `i32`. A constant with an explicit type, `const LIMIT: u8 = 64`, has that type.
Fixed-array lengths accept integer literals, integer constants, parentheses, and
nonnegative integer arithmetic. Runtime values and calls are not allowed in array
lengths. See [memory patterns](memory-patterns.md) for supported
operators, evaluation limits, and runnable examples.
Runtime initializers execute once before `main`, after every initializer they reference. Ordering
between otherwise independent globals is deterministic canonical module/source order but programs
must not use that order as synchronization or as an implicit dependency. Cycles are rejected.

Function types are written `fn(ParamTypes) Result`; omitted result means `void`. A function
value is a code pointer, so there is no `*`; `*fn(...)` is a pointer to a function value.
Parameters may be named for documentation, as in `fn(target: *Entity, damage: i32) bool`; the
names do not affect the type. A function's name is its value: write `step: fn(u64) u64 = keeper`;
`&keeper` is an error. Function pointers may be copied, stored in aggregates, and called with
ordinary call syntax. Signature mismatches are errors, and calling `nil` traps at runtime.

Foreign declarations use `extern fn local_name "link_symbol"(parameters) Result` and have no
body. Calls are statically type-checked like Dyn calls, while the explicit string names the linker
symbol and remains stable through module qualification. Link objects or archives are supplied with
repeatable `--link PATH`; ordinary programs acquire no foreign runtime dependency. Packages in the
`vendor/` collection declare their own native-library dependencies, so importing one may add its
documented runtime dependency automatically.
Foreign data uses `extern local_name "link_symbol": Type`. It names existing mutable native
storage, performs no initialization, and transfers no ownership.

Foreign declarations may end their parameter list with `...` for C ABI variadics. Calls require
all fixed parameters, apply C default promotions (`f32` and integer types narrower than 32 bits),
and otherwise accept only integers, `f64`, or pointers as variadic arguments. Taking a foreign
variadic function's address preserves that ABI and the same checks at indirect calls. Native
variadic function pointers remain unsupported because their borrowed-pack ABI differs. A Dyn
function declares a named final pack as `name: ...T`; in its
body that name is a borrowed `[]T`. Calls may supply zero or more trailing values. Typed packs apply
ordinary lossless conversion to `T`; `...any` preserves each concrete argument type for type cases.
Compiler-created pack/value storage lives in the caller stack frame, so the slice cannot outlive the
call and adds no heap allocation. The named pack is the only native variadic source interface.

`any` has the two-word representation `{type identity, data pointer}`. Boxing places a copy of the
source value in current storage and the `any` points to that copy. Copying an `any` is shallow: it
copies both words, not the referenced value. Globals and direct function results of type `any` are
rejected. Consequently an `any`, a native variadic pack, and a
value extracted from that pack are borrowed and must not outlive the boxing call/frame or borrowed
source. The compiler diagnoses some directly proven local return escapes but does not provide complete lifetime analysis; violating this rule is the same class of
program error as retaining an ordinary dangling pointer. Type cases are the only checked unboxing
operation.

## Generic functions

A function, struct or enum takes type parameters in angle brackets after its name:

```dyn
fn max<T>(a: T, b: T) T {
  if a > b { return a }
  return b
}

fn first<T>(items: []T) T {
  return items[0]
}
```

A call infers the type arguments from its arguments when every type parameter appears in a
parameter's type: `max(x, y)`, `sort.sort(values)`. Arguments must agree exactly, with no implicit
widening; a number literal or `nil` takes the type the other arguments give, so
`thread.spawn(arena, stack, worker, nil)` infers `C` from `worker`. `max(x, y)` with `x: i32` and
`y: i64` is an error (`T is both i32 and i64`); cast one argument. When a type parameter appears
only in the result or the body, the call writes the arguments: `mem.push<Node>(arena)`,
`size<u8>()`. Explicit arguments are always allowed, as in `max<i64>(1, 2)`.

Each distinct set of type arguments makes one instance, and the compiler checks each instance's
body as ordinary code: a body that is invalid for a type is an error at the call that created the
instance. There are no constraints, traits, interfaces, operator overloading or compile-time
execution, and types are inferred only from arguments, never from the expected result, with one
exception below. The [generics design](../internals/generics-design.md) records the rules and what
is deliberately left out.

A generic function used as a value names its instance: `hash := key_hash<u32>`. Where a function
type is expected, the instance comes from that type instead: with
`fn key_hash<K>(seed: u64, key: K) u64`, `hash: fn(u64, u32) u64 = key_hash` is the `u32`
instance, and so is passing `key_hash` to a parameter of that type. A call `f(...)` always runs
the function.

`case T` chooses code by type, at compile time, inside a generic body. Its arms are types and `_`;
only the matching arm is compiled for an instance, so the other arms may use operations that type
does not have:

```dyn
fn width<T>() usize {
  case T {
    u8 => { return 1 }
    u16 => { return 2 }
    _ => { return #sizeof(T) }
  }
}
```

`#assert` also works in a function body, where it is checked when the body is: in a generic
function, once per instance. With `#typeof`, whose scalar fields (`kind`, `size`, `id`,
`element_id` and the rest) are compile-time constants, it states what a generic function accepts:

```dyn
fn bits<K>(key: K) u64 {
  #assert(#typeof(K).kind == TypeKind.Integer, "bits: K must be an integer")
  return #cast(u64, key)
}
```

When an `#assert` in a body fails, that function's other errors are not reported: they would only
restate that its type arguments are wrong. An `if` whose condition is a compile-time constant
compiles to the branch it takes; both branches must still type-check for the instance, so this
removes dead code but never chooses code by type. `case T` is the way to choose by type.

A struct or enum may take type parameters, and each set of arguments makes one concrete type:

```dyn
struct Box<T> { value: T, failed: bool }
enum Slot<T> { Empty, Full(T) }
type IntBox = Box<i32>

fn wrap<T>(value: T) Box<T> {
  result: Box<T>
  result.value = value
  return result
}

a := Box<f64>{ value: 1.5 }
b := IntBox{ value: 1 }
s := Slot<i32>.Full(7)
```

Type arguments are always written where a generic struct or enum is named, as in `Box<i32>{...}`,
`Slot<i32>.Full(7)` and `case` arms such as `Slot<i32>.Full(v)`; inside a generic function they are
the function's parameters, `Box<T>`. A module-level alias gives an instance a short name.
`mem.push<Box<i32>>(arena)` passes the instance as a type argument.

The older spellings are errors with a fix in the message: `$T` in a parameter type, `T: type`
parameters, `Box(T)` declarations and `#instance(f, T)`.

## Values and types

A string is a `[]const u8`: pointer and byte count, no trailing zero. The type does not
guarantee UTF-8. Source files and literal text are UTF-8, but `\x` escapes can write any byte,
and bytes read from files, sockets, or the OS arrive unchecked. Text APIs that require UTF-8
say so and validate; check external input with `utf8.valid` from `std/unicode/utf8` before
treating it as text. `const` prevents writes through this view only: another `[]u8` alias of the
same memory can still change the bytes. Character literals are untyped integer constants holding a Unicode scalar value:
they take any expected integer type the value fits, and default to `u32`. `str` is a built-in
alias for `[]const u8`, so `names: []str` and `fn greet(name: str)` read well.

A backtick string, `` `C:\temp\n` ``, is raw: no escape is processed and it may span lines, so
`` `a\nb` `` is four bytes and a multi-line template keeps its newlines.

`distinct`, `packed`, `union`, `nocopy` and `type` are reserved keywords and cannot be names.
`union` declares nothing; the one union Dyn has is a union of error enums, written `A | B`
(see [errors](#errors)).

`type` creates module-level transparent aliases; aliases may be forward-referenced and
alias cycles fail. There are no local aliases; declare them at module scope.
`distinct type Name = T` creates a nominal numeric type with `T`'s representation. Values cross
the distinct boundary only through explicit `#cast`; same-type arithmetic preserves the distinct
type. Structs/enums remain nominal.

A struct field may declare a default: `struct Player { health: i32 = 100, armor: i32 }`. Defaults
are compile-time values. Every fresh value of the struct takes them: a literal's omitted fields
(`Player{}` or `Player{armor: 5}`), a declaration without an initializer (`p: Player`), and
`mem.push(Player, arena)`. A declaration without an initializer is the one way to get a fresh
value: `buffer: [64]u8 = []` is an error because the `= []` adds nothing. A field without a default is zero, and an omitted struct-typed field is
that struct's own fresh value. `#init(pointer)` makes `*pointer` a fresh `T`, zero and then the
defaults, which is how `mem.push` and custom allocators make fresh values from uninitialized
memory; for a fixed-size `T` it compiles to stores in place. Zeroed bulk memory (`mem.push_array`, fixed arrays, `[]` initializers) stays zero: write
a loop when its elements need defaults. Unions have no defaults.

Implicit numeric conversion is allowed only when destination represents every source-type
value exactly. Constants adapt when their specific value fits, and a literal that does not fit
its context is a compile error, checked again for each type a generic function is called with.
An integer literal in a float context is that float when it is exact (up to 2^24 for `f32`,
2^53 for `f64`), so `x * 2` works for any numeric `T`. Integer overflow
wraps in every build; `--check-overflow` makes it panic instead (see [numeric rules](#numeric-rules)). Floats use IEEE-754. Expression evaluation is left-to-right.
A float literal with no float context is `f64`, so `x := 1.5` is `f64`.
A float literal needs a digit after the dot: write `2.0`, not `2.`, which is an error. `2..3` is an
integer range.
Explicit locals without initializers start at zero, or at their struct's field defaults.
Inferred locals require an initializer. Names never shadow: a local cannot reuse the name of
another local, parameter or loop variable that is still in scope, in the same block or a nested
one, and never the name of a global, function or module. A name becomes reusable after its block
or loop ends, so sibling blocks and consecutive loops may each declare `value`. Assignments copy values; compound assignments use
the same checked operators as ordinary expressions. An assignment evaluates its target (indexes,
pointer operands) before its value: in `a[i()] = f()`, `i()` runs first. A compound assignment
evaluates its target once, so `a[i()] += f()` calls `i()` once. Struct literal fields evaluate in
written order, not declaration order.

`if` and condition-form `for` require `bool`. Bare `for {}` is an infinite loop. `break` and
`continue` require an enclosing loop. Block locals are inaccessible after block exit. `for value in
collection` accepts arrays and slices, evaluates the collection once, and copies each element into
the loop-local binding. `for *value` binds a pointer to each source element. The pointer is `*const` when the collection is
a const slice, so writing through it is an error there; arrays must be assignable.
`for value, i in values` (and `for *value, i`) also binds the element's index as a `usize`; with
`#reverse` the index still names the element's position. A range loop's variable is already its
index, so a range takes no second name.
`for i in first..last` counts integers from `first` up to but excluding `last`; `..=` includes
`last`. Both bounds share one integer type, and a literal bound adapts to the other bound, so
`0..count` has `count`'s type. When both bounds are literals, `i` is a `usize`, whatever the
body does with it, so `for i in 0..3 { values[i] }` indexes directly. A typed binding sets the type
of both bounds: `for i: i32 in -3..3` or `for i: i32 in 0..5 { total += i }` with `total: i32`.
A negative literal range needs a typed binding. Bounds evaluate once, first
bound first. An empty range such as `5..2` runs no iterations. `i` is a copy: assigning it does not change iteration, and pointer
bindings are rejected. Inclusive ranges may end at the type's maximum without overflow.
`for i in #reverse(first..last)` visits the same values from last to first: `#reverse(0..3)` gives
2, 1, 0 and `#reverse(1..=3)` gives 3, 2, 1. A descending range stays empty with or without
`#reverse`. `for value in #reverse(values)` and `for *value in #reverse(values)` visit array or
slice elements from last to first. `#reverse` is valid only as a `for` iterable and never wraps an
unsigned bound. `for i in #step(first..last, n)` visits `first`, `first + n`, and so on while the value
is in the range: `#step(0..10, 3)` gives 0, 3, 6, 9 and `#step(0..=10, 5)` gives 0, 5, 10. The step
has the range's type and must be positive; a constant zero or negative step is an error, and a
zero step at run time divides by zero. Bounds and step evaluate once, in order, and the counter
never passes the type's limit, so `#step(250..=255, 2)` on a `u8` stops at 254. `continue` moves
to the next value. `#reverse(#step(0..10, 3))` visits the same values from the last: 9, 6, 3, 0.
`break` and `continue` act on the innermost loop. A label before a loop lets them name an outer
one: `outer: for row in rows { for cell in row { if cell == 0 { continue outer } } }`. Transfers run
defers for every exited scope.

Struct field order determines layout. Packed structs preserve order, remove inter-field padding,
and have alignment 1. Construction gives every field its default (zero when it declares none), then
applies explicit literal members. A literal always names its type:
`Point{ x: 1 }`. Struct assignment copies by value. Unknown/duplicate fields, duplicate declarations,
by-value recursion and aggregate comparison fail. Empty structs have size and alignment 1 so arrays
have stable element stride and distinct elements have distinct addresses.

An `if`, `for` or `case` header cannot hold a bare struct literal, since its `{` would read as the
body: write `if p == (Point{ x: 1 }) { ... }`.

`nocopy struct File { ... }` makes a type that owns something, such as a handle or an arena, and
must not be duplicated. Copying a value of it is a compile error: binding it to a new name,
passing it by value, assigning it, or reading it through a pointer with `p.*`. The rule carries
over to every struct, array or enum that contains one. Pass `&file` to borrow it. `#take(&file)`
moves the value out and leaves `file` fresh, as a declaration without an initializer would, so the
old name can no longer close the same handle. A function may still return a `nocopy` value it made.
`mem.Arena`, `heap.Heap` (`std/mem/heap`), `sync.Channel<T>`, `thread.Scope` and `fiber.Fiber` are `nocopy`.

Dyn has no general union types. Reinterpret a number's bits with `#bitcast`, and store one of
several shapes in a payload enum. To match a C union's layout, declare a field of the largest member's
size and alignment, such as `[4]u32` for a 16-byte, 4-aligned union.

Functions may accept and return primitive or struct values. Arguments evaluate left-to-right and
must match declared parameter count/types, subject to normal lossless conversions. Non-void
functions must return on every reachable exit. A `for` with no condition and no `break` is not
an exit, so a function may end with one; code after it is allowed but never runs. Calling a non-void function as a statement is an
error; use `_ = call()` to discard its result. Forward calls and direct recursion are supported.

Enums are nominal. Tags default to `u32` or use an explicit integer backing type, as in
`enum(u8) Op`. Variants take tags 0, 1, 2 and so on in declaration order. A plain enum may set
tags to match external numbers: `enum(i32) Errno { Ok = 0, NoEnt = 2, Intr = 4, Io, NoMem = 12 }`,
where an unset tag is the previous one plus one (`Io` is 5). Set tags are constant integers, must
increase, and the first must be 0, so zeroed storage (`x: Color`, omitted struct fields,
`mem.push`) always holds the first variant; make that variant mean empty, `Null` or `Ok`. Enums
with payloads keep automatic tags. `enums.from_int(Errno, n)` turns an external number into the
variant with that tag, or the first variant when none has it; dense enums check a range and enums
with set tags search their variants. Variants are written `Enum.Variant`. Where exactly one enum type is expected, in an assignment,
a return, a struct literal field, an argument, a comparison with an enum value, `fail` or a
`case` arm, `.Variant` is enough:
`c: Color = .Green`, `fail .NotFound`. On a union `A | B` the enum is always written. Enums support
equality and copy by value. `#cast(u8, op)` gives the tag. An integer
becomes an enum only through `enums.from_int(Op, byte)`, which gives the first variant for a tag
that names none; `#cast(Op, byte)` is an error. An exhaustive `case` that meets a tag matching no
variant panics with `enum.tag.ok`. Enums without payloads have the size and alignment of the
backing integer.

A variant may hold one typed value: `enum Node { Null, Number(f64), Link(*Node) }`. Build one with
`Node.Number(2.5)`. The first variant may carry a payload too; zeroed storage holds the first
variant with a zero payload. A `case` arm is the only way to reach a payload:
`Node.Number(value)` copies it, and `Node.Number(*value)` binds a real `*f64` to it, written through
with `value.* = ...`, and needs a mutable subject. Replacing the enum while an alias is live leaves the alias on the
old variant's storage, the same class of error as a dangling pointer. Enums with payloads have
no `#cast` and no `==`; they are laid out as the tag followed by the largest payload.

An enum can take type parameters: `enum Slot<T> { Empty, Full(T) }`. Write the arguments
everywhere the enum is named: `Slot<i32>.Full(7)` builds one, and a `case` arm reads
`Slot<i32>.Full(value)`. Inside a generic function, use `Slot<T>`. `type IntSlot = Slot<i32>` gives
a shorter name, and `IntSlot.Full(7)` works. A generic function infers `T` from a parameter such
as `slot: Slot<T>`.

Bit masks use distinct unsigned integer types, not special flag-enum syntax. Values explicitly
cast into the mask type; ordinary integer `|`, `&`, `^`, and `~` then preserve its nominal type.
Enums remain single-choice values.

Pointers are thin and zero-initialize to `nil`. `&value` requires assignable storage; `pointer.*`
dereferences it. Struct fields automatically dereference struct pointers. Dereference checks nil
and pointee alignment, then panics on failure. Pointers support equality with compatible pointers or `nil`, and ordering with `<`, `<=`, `>` and
`>=`. There is no pointer arithmetic: `#slice(pointer, count)` makes a slice you vouch for, and
indexing it is bounds checked against that count. Mutable pointers implicitly widen to
`*const T`, never back to mutable. Shallow const forbids replacing fields through the const pointer,
while a mutable pointer stored in such a field still permits mutation of its own pointee:

```dyn
fn touch(o: *const Outer) {
  o.inner.n += 1 // allowed: inner is *Inner
  o.count = 1    // error: assignment through *const pointer
}
```

`rawptr`
is untyped storage and cannot be dereferenced; explicitly cast it to a typed pointer before access.
A mutable `*T` converts to `rawptr` implicitly, as C's `void *` does: `free(task)` needs no cast.
The reverse, `rawptr` to `*T`, always requires `#cast`. `*const T` does not convert implicitly.

`&` takes the address of a local, a global, a field, an element, or a struct literal. `&Point{x: 1}`
points at the literal's own storage, which lives until the end of its block, like a local declared
there. In a loop each iteration fills the same storage again. `return &Point{x: 1}` is an error,
as `return &local` is. A call result has no storage of its own,
so `&f()` is an error; bind it first (`p := f()`, then `&p`). The compiler also rejects storing a
local's address through a parameter or into a global, where it would outlive the function.

Pointers are thin. Dereference checks nil and alignment, but not lifetime or allocation
bounds. Thin pointers cannot be indexed or sliced with `[..]`. `#slice(pointer, count)` makes a slice
from a pointer and a length the compiler cannot verify, so a wrong count reads out of bounds. Slices are `{data, len}` descriptors and are
never comparable. Fixed arrays copy by value; omitted literal elements zero-fill, including typed
`[]`. Array/slice indexing is bounds-checked. Indexes and slice bounds accept any integer type no wider than `usize`, as in C; a negative signed value fails the bounds check like any other out-of-range index. Use `#cast` for wider types, such as `i64` on 32-bit targets. Exclusive ranges support `[..]`, `[..end]`,
`[start..]`, and `[start..end]`, checking `start <= end <= len`. `xs.len` is the length of an array
or slice, a `usize`. Slices are not comparable with `==`; `slice.eql<T>(a, b)` from `std/slice` and
`bytes.equal` compare contents.
`rawptr` has no direct indexing or slicing. Cast it explicitly to `*T`, then use
`#slice`: `#slice(#cast(*T, memory), count)`.
`rawptr` has native pointer size/alignment, zero-initializes to `nil`, and supports equality and
an implicit conversion from mutable typed pointers, and explicit casts to/from compatible typed
pointers or native-width integers. It has no pointee,
ownership, lifetime, arithmetic, indexing, or dereference operation.

## Control flow and cleanup

Each statement starts on its own line; two statements on one line are a syntax error. A newline
ends a statement except inside `(...)` and `[...]` and right after a `,`, a `{` or a binary
operator, so a long expression continues after `+` or `&&`, or inside parentheses. A block
with a single statement may stay on one line, as in `if done { return }`, and so may an `if` whose
two branches are one statement each: `if wide { return 8 } else { return 4 }`. `case` arms are not
separated by commas; each arm's body is a block:

```dyn
case kind {
  0 => { return "none" }
  1 => { return "one" }
  _ => { return "many" }
}
```

Every `case` is exhaustive or contains `_`; integer interval analysis may prove exhaustive
coverage. A case on text, a `[]const u8` or `[]u8` subject, takes string literal patterns and
always needs `_`; arms take no binding. It evaluates the subject once and makes no calls. Up to
four patterns are compared in order, length first, then bytes. With more, it dispatches like an
integer case: on the length, then on the bytes that tell the remaining patterns apart, and
compares the rest of the one candidate left, so a lookup costs about the same for 5 arms or 500.
Patterns never overlap, so the order cannot change which arm runs:

```dyn
fn command(word: []const u8) i32 {
  case word {
    "go", "run" => { return 1 }
    "stop" => { return 2 }
    _ => { return 0 }
  }
}
```
 Integer and enum patterns use literals or constants; text patterns are string literals. Arm
order is irrelevant; duplicates,
overlaps, unreachable `_`, and redundant `_` fail. `Variant(payload)` copies its payload.
`Variant(*payload)` binds a pointer to the payload storage, used as `payload.*` or for field
mutation; it requires a mutable assignable case subject. The pointer is valid only inside its arm.
Enum cases may be exhaustive by listing every variant. Integer cases may be exhaustive by covering
the whole representable interval. Because the set of Dyn types is open, an `any` type case always
requires `_`. Type patterns are written as the type with an optional binding in parentheses:
`i64(n) => { ... }`, `[]const u8(text) => { ... }`, `Point(p) => { ... }`; a pattern that names a
type is a type pattern. They neither implicitly cast nor match aliases by spelling: they compare the
boxed concrete type identity and bind a copied value of that exact type. A literal boxed into
`any` takes a default type, as in Go and Odin: an integer is `i32`, a float `f64`, a string
`[]const u8`, a character `u32`.

A bare block, `{ ... }` on its own as a statement, opens a scope: its locals end at the closing
brace and its defers run there. Use it to hold a lock or other resource for part of a function:

```dyn
fn sign_up(app: *App, name: []const u8) i64 {
  id: i64 = 0
  {
    sync.lock(&app.lock)
    defer sync.unlock(&app.lock)
    id = insert_user(app, name)
  }
  return start_session(app, id) // takes app.lock again
}
```

A bare block costs nothing; it compiles as `if true { ... }`, and a block that returns ends the
function.

`defer` runs at enclosing-block exit in LIFO order. Direct-call arguments evaluate at defer
site. Deferred blocks observe captured storage at execution. Deferred statements exclude
`return`, `break`, `continue`, declarations, and nested `defer`. `errdefer` is a `defer` that runs
only when the function leaves by failing (see [errors](#errors)).

A panic does not run defers. It runs the handler that `std/panic` installs with
`panic.set_handler(report)`, prints the message and a stack trace, and exits with status 101. The
handler runs once, for work the operating system will not do at exit, such as restoring a
terminal's mode, logging or flushing a crash report; it cannot resume the program. The operating
system frees memory and closes files when the process ends. There is no recovery mechanism: a
panic is a bug, and expected failures are values.

## Errors

A function that can fail says so in its result type. `T!E` returns a `T` or fails with an `E`;
`!E` returns nothing or fails with an `E`. `T!` and `!` fail with no value, for code that has only
one way to fail, such as a cipher given a bad key:

```dyn
fn port(text: str) u16!parse.ParseErr {
  value := try parse.u64_decimal(text)
  if value > 65535 { fail .TooLarge(0) }
  return #cast(u16, value)
}
```

`E` is an enum, usually with payloads (`io.IoErr`, `parse.ParseErr`, or one of the program's own),
or a union of enums, `A | B`, written in parentheses in a result type, `!(io.IoErr | StoreErr)`, and
nameable with a module-level alias: `type AppErr = io.IoErr | ParseErr`.
A union is flat and unordered: `A | B` is `B | A`, `(A | B) | C` is `A | B | C`, and `A | A` is `A`.
Failure is a return value with no unwinding and no allocation: a fallible result is the value or
the error and one flag.

- `fail value` returns the error. `fail .Variant` uses the shorthand when the error type is one
  enum; a union needs the enum written, `fail StoreErr.BadLine(n)`. In a `T!` or `!` function,
  `fail` takes no value.
- `try call()` passes a failure on to the caller, running `defer` and `errdefer` on the way. It is
  allowed only in a fallible function, and the callee's error must fit the caller's: an `E` widens
  to any union that contains it, with no conversion code.
- `call() catch fallback` gives a value of the result type instead of failing; the fallback is
  evaluated only on failure. `call() catch {}` ignores the failure of a call that returns nothing.
- `call() catch err { ... }` handles the failure with `err` bound to the error. On a call that
  returns a value, the block must leave the enclosing code: `return`, `fail`, `break`, `continue`
  or `#panic`. To make a value from a failure, return it from a small function.
- `case err` matches the error: variants such as `.NotFound`, payloads such as `.Invalid(at)`,
  and on a union whole constituents, `io.IoErr(read) =>`, or single variants, `StoreErr.BadLine(n) =>`.
- `errdefer statement` runs when the function fails after it, and not when it returns normally.
  Use it to release what a constructor acquired before a later step failed.

A fallible result must be handled: a call whose failure is neither passed on with `try` nor
handled with `catch` is an error, and so is discarding it with `_ =`. In an `if` or `for` header,
put a `catch` fallback in parentheses: `if (sqlite.first(lookup, id) catch false) { ... }`.

## Numeric rules

Integer widths are fixed except `isize`/`usize`, which match the target pointer width. Signed values
use two's-complement representation. `+`, `-`, `*`, `<<` and unary negation wrap at runtime; overflow
in a constant expression is a compile error. Shift counts are masked to the left operand's width, so
`x << 33` on a `u32` shifts by 1. Right shift is arithmetic for signed and logical for unsigned
values. Bitwise operators require integers. Division and remainder by zero panic, and the signed
minimum divided by `-1` panics. `std/math` has `add_overflows`, `sub_overflows`, `mul_overflows` and
saturating arithmetic for code that wants them.

Integer arithmetic wraps in debug and release builds alike. `--check-overflow`, in either mode,
makes `+`, `-`, `*`, `<<`, unary negation and their compound assignments panic with
`overflow.ok` instead of wrapping, in every module, std and vendor included. Write
`#wrapping(expr)` where code means to wrap, such as a hash or a rotation: its integer arithmetic
wraps even in a checked build, and it compiles to the same instructions as without it. Calls
inside it keep their own rules. `math.wrapping_add`, `wrapping_sub` and `wrapping_mul` do the same
as functions. The checks find overflow bugs; they do not change
the meaning of a correct program.

Untyped integer constants are evaluated exactly for the implemented constant-expression operators,
then adapted only when their value is representable in the expected type. Runtime implicit numeric
conversion is allowed only when every source-type value is exactly representable on every
target, counting `usize` and `isize` as anywhere from 32 to 64 bits: `usize` widens to `u64` and
`u32` to `usize` implicitly, while `u64` to `usize` needs `#cast`. The same rule joins
the operands of a binary operator: when one operand's type widens to the other's without loss,
the operator works in the wider type, so `count_u32 * size_u64` is a `u64` and `index_u32 < limit_i64`
compares as `i64`. Arithmetic is target-typed: where the value goes into a wider number type (a
typed variable, an assignment, a field, an argument or a result), the operators compute in that
type, so `total: u64 = a_u32 * b_u32` multiplies in `u64` and cannot wrap at 32 bits. Integers
widen only to integers and floats only to floats; `#cast` and `:=` give no target, so
`n := a_u32 * b_u32` is a `u32`. Write the narrow type explicitly where wrapping is meant, as in
`hashed: u32 = value * 2654435761`. `x += y` widens `y` to `x`'s type the same way. Shifts keep
their rule: the result has the left operand's type, or the target's when that is wider.
A comparison of a signed and an unsigned integer compares their values: `-1 < len` is true for a
`usize` `len`, and `i64` against `u64` needs no cast. One operand is read twice, so at least one
side must contain no calls; otherwise store a value in a name first. Arithmetic between `u64` and
`i64` still has no lossless meeting type and needs a cast. Three operators show their result's
range in the code, so they narrow without a cast where a smaller integer type is expected and the
range fits it: `x & M` with a constant `M` (`b: u8 = word & 0xff`), an unsigned `x >> k` with a
constant `k` (`top: u8 = x_u64 >> 56`) and an unsigned `x % M` with a constant `M`. Nothing
else narrows implicitly; a range known only from a condition, as in `if x < 256 { ... }`, still
needs `#cast`. `#cast` permits
intentional narrowing and uses destination-width two's-complement/modulo representation for integers.
Float-to-integer conversion truncates toward zero and saturates: an out-of-range value gives the
type's minimum or maximum, and NaN gives 0, on every target. `#bitcast` preserves bits and requires
numbers of equal size; pointers convert only with `#cast`. Boolean/numeric conversion is never implicit.

Empty or partially specified fixed-array constants zero-fill omitted elements. Compiler work and IR
for an empty aggregate must remain bounded by written initializer count rather than storage size.

## Operator precedence

Postfix forms bind tightest: calls, indexing, slicing, and field access. Prefix `-`, `!`, `~`, and
`&` come next and apply to the whole postfix chain, so `-a[i]` is `-(a[i])`. `#cast(T, value)` and
other builtins are self-delimiting and act like primary expressions.

Binary operators, tightest first. Every binary operator is left-associative.

| Level | Operators |
| --- | --- |
| 1 | `*` `/` `%` |
| 2 | `+` `-` |
| 3 | `<<` `>>` |
| 4 | `&` |
| 5 | `^` |
| 6 | <code>&#124;</code> |
| 7 | `<` `<=` `>` `>=` |
| 8 | `==` `!=` |
| 9 | `&&` |
| 10 | <code>&#124;&#124;</code> |

Mixing a bitwise operator (`&`, `^`, `|`) with a comparison needs parentheses:
`flags & mask == 0` is an error and `(flags & mask) == 0` is required, so the expression means
the same thing to readers from every language.

Comparisons do not chain: `0 <= i < n` is an error, written `0 <= i && i < n`. Write
`(a == b) == c` when comparing a comparison's result is meant.

## Format templates

Formatting is ordinary library code: `io.println`, `io.print_to`, `strings.format` and
`fmt.print` take a template and `...any` values. `{}` inserts the next value and `{{` and `}}`
write a brace. A missing value prints `{?}`, an extra one prints at the end as `{+value}`, and a
value with no text form prints `{?}`. The compiler treats these functions like any other.
`dyn vet`, like Go's vet, checks calls that pass a literal with braces right before the values:
a lone brace or a `{}` count that differs from the number of values is reported.

A struct or plain enum value prints its contents, read at run time through its `TypeInfo`:
`io.println("{}", unit)` prints `Unit{name: ada, at: Vec2{x: 1.5, y: 2}, op: Sub}`. Any
expression works, such as `spot()` or `points[i]`, and each is evaluated once like any other
argument. An enum with a payload has no text form.

## Builtins

The `#` prefix identifies a compiler intrinsic or module directive. It does not
mean that the operation runs at compile time. Allocation, I/O, formatting,
collections, and ordinary algorithms belong in libraries.

- Conversion: `#cast(Type, value)` and `#bitcast(Type, value)`.
- Arithmetic that wraps on purpose: `#wrapping(expr)`.
- Layout and reflection: `#sizeof`, `#alignof`, `#offsetof`, and `#typeof`.
- Integer limits: `#max` and `#min`.
- Representation and pointers: `#slice` and `#init`.
- Ownership: `#take(&value)` moves a `nocopy` value out and leaves `value` fresh.
- Validation and termination: compile-time `#assert` and runtime `#panic`.
- Build input and OS boundary: `#load` and `#syscall`.
- Iteration: `#reverse` and `#step`, valid only in a `for` iterable.
- Floating-point operations the hardware has: `#sqrt`, `#floor`, `#ceil`, `#trunc`, `#round` and `#fma`.
- Module directives: `#target` and `#link`, documented with platform and FFI rules.

`#sizeof(T)` and `#alignof(T)` are the short forms of `#typeof(T).size` and `#typeof(T).alignment`.

`#sqrt(x)`, `#floor(x)`, `#ceil(x)`, `#trunc(x)` and `#round(x)` take and return `f64`; `#round`
rounds halves away from zero. `#fma(x, y, z)` computes `x * y + z` with one rounding, in `f32` or
`f64`. Each is one instruction where the target has it (`sqrt` everywhere with an FPU; the
rounding operations on AArch64, and on x86-64 with SSE4.1; `fma` on AArch64, RISC-V and x86-64
with FMA3) and a correctly rounded software routine elsewhere. The software comes with the
compiler, so these need no import; `std/math` wraps them for generic code.

`#target(key: value)` at the top of a file keeps that file only for matching targets. The keys
are `arch`, `kernel` (`linux`, `darwin`, `windows`, `wasi`, `none`, `browser`), `family` (`unix`
on Linux and macOS, so one file can hold POSIX code both share; the kernel name everywhere else),
`abi`, `libc`, `endian`, `pointer_bits` and `streams` (`yes` on every target with standard input,
output and error, which is every target but the browser).

Conversions require exactly two arguments, with the type first. The value may be
any expression and is evaluated exactly once. The closing parenthesis delimits
that expression: `#cast(i64, a + b)` converts the sum, while
`#cast(i64, a) + b` converts only `a`. Cast results accept ordinary postfix
operations, such as `#cast(*T, memory).field`. The old `#cast(T) value` and
`#bitcast(T) value` forms are rejected; see the
[migration guide](../migrations/cast-syntax.md).


`#sizeof(type_or_value)` and `#alignof(type_or_value)` return `usize` constants without evaluating
value operands. `#cast(T, value)` performs explicit numeric conversion
or compatible pointer conversion; explicit integer-pointer casts serve OS ABI boundaries. Narrowing follows destination representation. `#bitcast(T, value)`
requires numbers of equal size; it never takes pointers.
`#max(T)` and `#min(T)` are the largest and smallest values of integer type `T`, as constants of
type `T`; `#max(usize)` is the target's. `#syscall(number, args...)` returns `isize` and accepts at
most six integer/pointer arguments on
Linux x86-64. It does not depend on `std`. The number may be a named constant: `std/os/linux/sys`
and `std/os/macos/sys` name each call std makes, as in `#syscall(sys.Getpid)`.
`#offsetof(Type, field)` is a field's byte offset as a `usize` constant.
`#init(pointer)` is a statement that sets `*T` to a fresh `T`, as a declaration without an
initializer would: zero, then field defaults. It works for every type. `#take(&value)` returns
`value` and then does `#init(&value)`; it is how a `nocopy` value changes owner.
`#len(x)` and `#instance(f, T)` were removed; write `x.len` and `f<T>`.
`#assert(condition, "message")` fails compilation when a constant condition is false, at top level
or in a function body.
`#load("file")` embeds a file's bytes as a `[]const u8`; the path is relative to the module directory and may not contain `..`.

`#panic(message)` accepts any `[]const u8` expression; messages need not be literals.

`#typeof(type_or_value)` returns compiler-provided `TypeInfo` without evaluating value operands.
For a value of type `any` it is the boxed value's `TypeInfo`, found at run time: the compiler
keeps a table of the types the program boxes into `any` and the types inside them.
It requires no standard-library import. Metadata includes an ID (the same for a type and for an
`any` holding it; unique in a program, not stable across builds), `TypeKind`, name, size, and
alignment. Only types passed to `#typeof` emit name metadata. Bare function names are accepted.
Struct fields, enum variants, and function arguments expose immutable name/type-ID descriptors
(`TypeMember`); its `value` is a field's byte offset or a variant's tag;
recursive relationships use IDs rather than nested metadata.
`TypeInfo`, `TypeMember` and `TypeKind` are builtin type names: no module may declare a type with
one of them.

## Removed/deferred syntax

No `inline`, `thread_local`, `as`, wrapping operators such as `+%`, `~=`, C-style casts,
`.{ ... }` literals without a type, or chained comparisons.
`#cast(T, value)` and `#bitcast(T, value)` are explicit. Unary `!` is bool-only;
unary `~` is integer-only. Comments do not nest; whitespace is insignificant; semicolons are
unsupported.

The parser also recognizes reserved syntax for editor recovery. Parsing alone
is not a supported-feature claim:

| Syntax | Compiler status |
| --- | --- |
| Module-level transparent type alias | Supported |
| Local type alias inside a function | Reserved; diagnosed as unsupported |
| Enum declaration-order tags | Supported |
| Explicit enum values | Supported for enums without payloads |
| `.Variant` where one enum type is expected | Supported |
| `.{ ... }` without the struct type | Removed; write `Type{ ... }` |
| Several imports in one `use`, comma-separated | Supported, each alias before its path |
| Import alias after the path, `use "std/fs" fs` | Removed; write `use fs "std/fs"` |
| `Variant: T` payloads, `Variant name =>` bindings | Removed; write `Variant(T)` and `Variant(name) =>` |
| `$T`, `T: type`, `Box(T)` generics, `#instance` | Removed; write `<T>` |
| Trailing-dot floats such as `2.` | Removed; write `2.0` |
| `#len(x)` | Removed; write `x.len` |

`tests/expect/` checks these forms (`bare-variant.dyn`, `local-type-alias.dyn`). See
[toolchain and grammar provenance](tools.md) for generation/release checks.

## Build modes and syntax stability

Debug and release have identical language correctness semantics. Both retain division, bounds, nil
and alignment checks unless proven redundant. Debug records function
frames for panic diagnostics. Release omits that tracing and enables backend optimization/internal
linkage; it may therefore show fewer diagnostic frames, never different valid results.

Core syntax is frozen for the current `0.1` release cycle. A syntax addition requires a language
decision, grammar/editor updates, positive and negative tests, and release notes. Library growth does
not justify new syntax when existing functions/types express the idea.
