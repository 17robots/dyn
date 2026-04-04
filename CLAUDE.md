# CLAUDE.md — Dyn Language Guide for AI Assistants

Dyn is a systems language: no GC, no hidden allocations, explicit
ownership. Source files end in `.dyn`. The reference compiler is written
in Rust (`src/`); a self-hosted compiler lives in `compiler-dyn/`.
Linux x86_64 only for now.

---

## Module system

Every file begins with `module name`. Files in the same directory with
the same module name are merged into one namespace. `use` is an
expression — assign it at module level or inline inside functions:

```dyn
io  := use "std/io"
os  := use "std/os"
str := use "std/str"

example := () {
    local_io := use "std/io"   // also valid inside a function
    local_io.println("hi")
}
```

`pub` exports a name. Everything else is private to the module.

---

## Variables & mutability

```dyn
x := 42           // immutable, type inferred
y: i32 = 42       // immutable, explicit type
mut z := 0        // mutable

// Nullable locals MUST be mut AND have an explicit type annotation
mut result: ?i32 = null

// Module-level mutable state also requires mut:
mut global_count: usize = 0
```

---

## Destructuring

```dyn
// Positional (tuple-style)
{a, b} := get_pair()       // a = index 0, b = index 1

// Named fields — binds by matching field names on the RHS
{x, y} := point

// Mix of mut and immutable
{mut a, b} := expr

// Ignore a field
{a, _} := pair
```

---

## Data types

```dyn
// Integers — arbitrary bit-width
n: i32  = -1
u: u64  = 0xdeadbeef
p: usize = $as(usize, ptr)   // pointer-sized unsigned
s: isize = -1                // pointer-sized signed
odd: i31 = 0                 // non-power-of-two widths are valid

// Floats
f: f32 = 3.14
d: f64 = 3.14159265358979

// bool is u1 — true/false are u1 literals
flag: bool = true
flag: u1   = true   // same thing

// void — absence of value; omitting return type is equivalent
noop := () void {}
noop := () {}       // same

// Arrays (fixed size) vs slices
arr: [4]i32  = [1, 2, 3, 4]   // fixed, lives on stack
sl:  []i32   = arr[..]         // slice of the whole array
sub: []i32   = arr[1..3]       // sub-slice [1, 2]
sub: []i32   = arr[1..=3]      // inclusive [1, 2, 3]

// Zero-initialize a fixed array with [...]
buf: [4096]u8 = [...]          // all zeros

// Slice fat-pointer fields (available on any []T value):
s.ptr   // *T    — pointer to first element
s.len   // usize — number of elements

// Vec exposes its contents as a slice via .slice():
mut v := Vec(i32).init(alloc)
v.push(1)
items := v.slice()   // []i32 — valid until next push or deinit

// Tuples — anonymous positional structs
t := {1, true, "x"}
a := t[0]   // 1   (compile-time index)
b := t[1]   // true
```

Arithmetic **wraps silently** on overflow — there are no overflow traps.

---

## Optionals

```dyn
// 1. Simple fallback value — no block needed for a single expression
len := maybe_len or 0
ptr := find_item(key) or default_ptr

// 2. Block fallback — use when you need multiple statements
val := parse(s) or {
    log_error(s)
    break 0
}

// 3. Early exit — null means nothing to do
item := get_item(id) or return
node := list.next(cur) or break

// 4. Safe unwrap with binding
if result: |v| {
    process(v)
}

// 5. Discard the value but check non-null
if result: |_| do_thing()

// 6. Enum tag comparison (no capture needed for payload-less variants)
if kind == .eof { return }
if kind != .ident { skip() }

// 7. Enum variant check with payload capture
if token == .ident: |name| { use_name(name) }
if token == .ident: |_|    { handle_ident_without_text() }

// 8. Multi-condition && with captures
// Each capturable sub-condition (?T or enum-with-payload) MUST have a slot.
// Non-capturables (bool exprs, payload-less enum checks) contribute no slot.
// Use _ to explicitly discard a slot.
if opt && e == .ident: |v, name| {}       // two capturables → two slots required
if opt && e == .ident: |_, name| {}       // discard opt's value
if count > 0 && maybe_item: |item| {}     // bool has no slot; only 1 capturable
if a_opt && b_opt && e == .ident: |a, b, name| {}

// Without `: |...|` — all conditions are plain bool checks; no values extracted
if opt && kind == .ident { handle_it() }  // just checks truthiness

// && short-circuits left-to-right; else runs on first failure
if heavy_check() && maybe_result: |r| {
    use(r)
} else {
    handle_absent()
}
```

Never use `.?` (force unwrap) unless the value is provably non-null
just above the call site. Prefer `or return` / `or break` at
boundaries.

---

## Error handling

```dyn
// Simple fallback — no block needed for a single value
n := parse_int(s) or 0

// Block fallback
n := parse_int(s) or {
    os.eprintln("bad input")
    break -1
}

// Capture the error value
n := parse_int(s) or |err| {
    os.eprintf("parse failed: {}", err)
    break -1
}

// Propagate in an errorable function
n := parse_int(s).!

// Early return on error
parse_int(s) or return
```

Use `?T` for "might not exist". Use `T!E` for "might fail with a
reason". Don't reach for errorable just to carry a message — `?T` with
a side-channel `eprint` is often cleaner in a compiler.

Combined `?T!E` — the `!E` layer is outermost, so handle it first:

```dyn
val := func().! or 0   // .! propagates/traps error, or 0 unwraps optional
```

---

## Defer

```dyn
// Always runs at end of scope (LIFO order)
defer { cleanup() }
defer { alloc.destroy_many(u8, buf) }

// Runs ONLY if the scope exits via an error
defer |e| { os.eprintln("rolled back due to error") }

// With explicit error type annotation
defer |e: ParseError| { report(e) }
```

Use `defer` for cleanup that should always happen. Use `defer |e|` for
rollback or logging that only matters on the failure path.

---

## Functions

```dyn
// Return type is REQUIRED for non-void functions
add := (a: i32, b: i32) i32 => a + b

// Arrow for single-expression bodies
clamp := (v: i32, lo: i32, hi: i32) i32 =>
    if v < lo lo else if v > hi hi else v

// Void: omit return type or write void explicitly
log := (msg: []u8) { os.println(msg) }

// Default arguments
connect := (host: []u8, port: u16 = 8080) ?Stream { ... }
connect("localhost")          // port defaults to 8080

// Named arguments at call site — any order
add3 := (x: i32, y: i32, z: i32) i32 => x + y + z
result := add3(z: 1, x: 2, y: 3)

// Extern (C interop)
execvp := extern (file: *any, argv: *any) i32 = "execvp"
```

---

## First-class functions & closures

`fn(params) ReturnType` is a type. Every function value is two words:
a function pointer and an environment pointer (null for non-capturing).

```dyn
// fn as a parameter type
apply := (x: i32, f: fn(v: i32) i32) i32 => f(x)

// fn as a struct field
Handler := struct {
    callback: fn(data: []u8) void,
}

// Non-capturing function assigned to fn type
double := (x: i32) i32 => x * 2
result := apply(5, double)

// Closure — captures n from enclosing scope
make_adder := (n: i32) fn(x: i32) i32 => (x: i32) i32 => x + n
add5 := make_adder(5)
result := add5(3)   // 8
```

---

## Structs

```dyn
// Basic definition
Point := struct {
    x: f32,
    y: f32,
}

// Field defaults
Config := struct {
    port:    u16   = 8080,
    verbose: bool  = false,
    name:    []u8  = "default",
}

// Instantiation forms
p  := Point.{ x: 1.0, y: 2.0 }   // named fields
p  := .{ x: 1.0, y: 2.0 }        // dot-inferred when type is known from context
p  := Point.{ 1.0, 2.0 }         // positional
c  := Config.{}                    // all defaults

// Packed struct (no padding, C-compatible layout)
Header := packed struct {
    magic:   u32,
    version: u8,
    flags:   u8,
}

// Type alias — transparent, interchangeable
IntList := List(i32)   // IntList IS List(i32)

// Newtype (distinct type)
Meters := struct { value: f32 }
```

Methods live inside the struct body. Use `$self()` for the self-type:

```dyn
Counter := struct {
    Self  := $self(),
    count: usize,

    init  := () Self => .{ count: 0 }
    inc   := (self: *Self) { self.count += 1 }
    value := (self: Self) usize => self.count

    // Returning an interface that wraps self
    writer := (self: *Self) io.Writer => .{
        ctx:   $as(*any, self),
        write: counter_write,
    }

    counter_write := (ctx: *any, buf: []u8) usize {
        self := $as(*Counter, ctx)
        self.count += buf.len
        return buf.len
    }
}

mut c := Counter.init()
c.inc()
os.println(c.value)
```

---

## Enums

```dyn
// Simple (no payload)
Direction := enum { north, south, east, west }

// With payload on some variants
Token := enum {
    ident:  []u8,
    number: i64,
    plus,
    eof,
}

// Explicit tag representation
Color := enum(u8) { red, green, blue }

// Instantiation
d   := Direction.north
tok := Token.ident("foo")
tok := .ident("foo")          // dot-inferred when type is known from context

// Matching — must be exhaustive
match d {
    .north: go_north(),
    .south: go_south(),
    .east:  go_east(),
    .west:  go_west(),
}

// Matching with payload binding
match tok {
    .ident:  |name| use_name(name),
    .number: |n|    use_num(n),
    .plus:          handle_plus(),
    .eof:           return,
}

// Wildcard catch-all
match tok {
    .eof: return,
    _:    skip(tok),
}
```

---

## Generics

Pass `comp type` for monomorphisation. Always define `Self` first.

```dyn
Stack := (T: comp type) type => struct {
    Self := $self(),
    buf:  ?*any,
    len:  usize,
    cap:  usize,

    init  := () Self => .{ buf: null, len: 0, cap: 0 }
    // ...
}

mut s := Stack(i32).init()
```

---

## Comptime

```dyn
// comp parameter — must receive a compile-time-known value
repeat := (s: []u8, n: comp usize) []u8 { ... }
repeat("ha", 3)   // ok — 3 is a literal
repeat("ha", n)   // error — n is runtime

// Force compile-time evaluation of an expression
pi := comp calc_pi()

// Comptime return type
best_float := () comp if use_f64 f64 else f32 => 3.14

// $self() inside a struct/type definition refers to the type being defined
Node := struct {
    Self  := $self(),
    next: ?*Self,
}
```

---

## Strings

Strings are `[]u8`. String literals are `[]u8`. Characters are `u8`.
There is no implicit null terminator.

```dyn
greeting: []u8 = "hello"
ch: u8 = 'h'

// C interop: null-terminate manually
buf := alloc.create_many(u8, path.len + 1) or return false
$memcpy($as(*any, buf.ptr), $as(*any, path.ptr), path.len)
buf[path.len] = 0

// Comparisons and utilities — use the str module
str := use "std/str"
if str.eq(a, b) { ... }
if str.starts_with(line, "//") { ... }
trimmed := str.trim(line)
```

---

## Pointers & pointer arithmetic

```dyn
// Address-of
p: *i32     = &x
q: *mut i32 = &mut_x

// Dereference
val := p.*
q.* = 42

// Pointer arithmetic: cast to usize, add offset, cast back
field := $as(*FieldType, $as(usize, base_ptr) + offset)

// Type-erased pointer (interfaces, raw memory)
raw   := $as(*any, some_ptr)
typed := $as(*MyStruct, raw)

// *mut T coerces implicitly to *T; reverse requires explicit $as
imm: *i32     = q          // ok
back: *mut i32 = $as(*mut i32, imm)  // explicit
```

---

## Built-in intrinsics

All builtins are prefixed with `$`.

```dyn
// Casting — required for all numeric conversions and pointer casts
n := $as(u64, my_u32)
p := $as(*MyStruct, raw_ptr)
v := $as(usize, some_ptr)       // pointer to integer

// Type info
sz  := $sizeof(MyStruct)         // size in bytes
al  := $alignof(MyStruct)        // alignment in bytes
off := $offsetof(MyStruct, field) // byte offset of a field
t   := $typeof(expr)             // type of an expression

// $sizeof accepts any type expression including slices and arrays:
$sizeof([]u8)      // 16 on x86_64 (two usizes: ptr + len)
$sizeof([4]i32)    // 16 (4 * 4 bytes)
$sizeof(T)         // size of a generic type parameter

// Memory
$memcpy(dst, src, byte_count)         // raw byte copy
$memset(dst, byte_value, byte_count)  // fill memory with a byte value

// Syscalls (Linux x86_64)
fd  := $syscall(2, path_ptr, flags, mode, 0, 0, 0)   // open
n   := $syscall(0, fd, buf_ptr, len)                  // read
$syscall(3, fd, 0, 0, 0, 0, 0)                        // close

// Assertions and errors
$panic("message")          // trap at runtime
$unreachable()             // mark a path that must never execute
$compile_error("message")  // fail compilation with a message

// Compile-time target info — returns builtin.Target
if $target().os == .linux { ... }
if $target().sanitize { ... }
if $target().arch == .x86_64 { ... }
```

### Compile-time reflection builtins

```dyn
// Iterate struct fields at compile time (inline for only)
inline for $fields(v): |f| {
    write_all(f.name)   // []u8 field name
    print(f.value)      // field value
}

// Classify a type for generic dispatch
comp match $typeclass($typeof(v)) {
    uint:  write_uint(w, $as(u64, v)),
    sint:  write_int(w, $as(i64, v)),
    float: write_float(w, $as(f64, v)),
    bool:  w.write_all(if v "true" else "false"),
    bytes: w.write_all(v),
    _:     ...,
}

$has_method($typeof(v), "write_to")  // true if type has a method named "write_to"
$typename($typeof(v))                // []u8 string name of a type
```

### `any` parameter type

`any` as a function parameter type accepts a value of any type at call time.
Inside the function, use `$typeof(v)` and `comp match $typeclass(...)` to
dispatch on what was passed. This is used in `io.Writer.print`, `os.println`, etc.

---

## Memory — which allocator to use

| Situation | Allocator |
|-----------|-----------|
| Phase-level allocations (AST nodes, IR, symbol tables) | `Arena` — reset between phases |
| Temporary work within a function or pass | `Arena` + `save`/`restore` + `defer` |
| Long-lived data needing individual frees (caches, dynamic maps) | `GpaAllocator` |
| Stack-backed, zero heap | `FixedAllocator` |
| One-off large raw page | `PageAllocator` |

```dyn
mem := use "std/mem"

// Arena: the primary allocator. Reserves virtual address space once;
// the kernel commits physical RAM lazily as you write to it.
// Pointers are stable — data never moves.
mut arena := mem.Arena.init()
defer arena.deinit()
alloc := arena.allocator()

// Scoped temporary allocations with save/restore:
mark := arena.save()
defer arena.restore(mark)   // everything after mark freed here
tmp := build_temp_index(alloc)
// tmp freed automatically when mark is restored

// Between compilation phases: release physical RAM, keep virtual mapping.
arena.reset()

// Fixed / stack-backed (zero heap overhead):
buf: [4096]u8 = [...]
mut fa  := mem.FixedAllocator.init(buf[..])
fa_alloc := fa.allocator()

// GPA for individually-freed long-lived allocations:
mut gpa := mem.GpaAllocator.init()
gpa_alloc := gpa.allocator()
// ...
leaks := gpa.deinit()   // 0 = clean
```

### ArenaPos — scoped lifetimes

`arena.save()` returns an `ArenaPos` that captures the current bump position.
`arena.restore(mark)` resets the position to that value, freeing everything
allocated since the save. This is O(1) and composes naturally with `defer`:

```dyn
// Two-arena pattern for a compiler:
mut perm    := mem.Arena.init()   // long-lived: AST nodes, IR
mut scratch := mem.Arena.init()   // temporary: tokens, scratch buffers
defer perm.deinit()
defer scratch.deinit()

// Per-file compilation:
file_mark := scratch.save()
defer scratch.restore(file_mark)  // scratch freed after each file

tokens := lex(src, scratch.allocator())  // temporary
ast    := parse(tokens, perm.allocator()) // permanent
```

---

## Control flow

Braces are **optional** for single-statement bodies:

```dyn
// Single-line if
if x < 0 return -1
if found do_thing()
if err os.eprintln("failed")

// Single-line if/else
if x > max x = max else x = min

// Single-line for
for i < len: i += 1
for 0..len: |i| process(arr[i])

// Multi-statement still requires braces
if condition {
    do_a()
    do_b()
}
for i < len: {
    process(i)
    i += 1
}
```

Loop forms:

```dyn
// While-style
mut i := 0
for i < len: {
    // ...
    i += 1
}

// Range (exclusive / inclusive)
for 0..len:  |i| process(arr[i])
for 0..=len: |i| process(arr[i])

// Slice/array iteration
for items: |item| process(item)

// Infinite
for {
    line := read_line() or break
    handle(line)
}
```

Labeled blocks and labeled break/continue:

```dyn
// Break out of a named block with a value
result := outer: {
    for 0..n: |i| {
        if check(i) break :outer i
    }
    break :outer -1
}

// Continue a specific enclosing loop
outer: for 0..rows: |r| {
    for 0..cols: |c| {
        if skip(r, c) continue :outer
        process(r, c)
    }
}
```

Match — must be exhaustive:

```dyn
match tok.kind {
    .ident:  handle_ident(tok),
    .number: handle_number(tok),
    _:       skip(tok),
}

// With payload
match result {
    .ok:  |v|   use_value(v),
    .err: |msg| report(msg),
}

// Range patterns
match byte {
    0..=9:   handle_digit(byte),
    10..=12: handle_whitespace(byte),
    _:       handle_other(byte),
}
```

---

## Comments

```dyn
// Line comment — ignored
/* block comment — ignored */
/// Doc comment — attached to the next declaration by the parser
```

---

## Common pitfalls

- **`?T` locals need `mut` and an explicit type**: `mut x: ?i32 = null`, not `x := null`
- **No implicit bool**: `bool` is `u1`; `true`/`false` are `u1` literals
- **No implicit null termination**: string literals and slices never add `\0`; add it manually before any C call
- **`use` is an expression**: assign it at module level for reuse; inline use inside a function is fine but scoped
- **Return type required**: non-void functions must declare their return type; the compiler does not infer it from the body
- **`$as` for all casts**: there are no implicit numeric widening casts; write `$as(u64, my_u32)` explicitly
- **Wrapping arithmetic**: integer overflow wraps silently; there are no overflow traps by default
- **`or value` vs `or { break value }`**: use the bare form for a single fallback expression; only wrap in a block when you need multiple statements
- **`?T!E` order**: `!E` is outermost — handle the error first (`.!` or `or |e|`), then handle the optional
- **Match exhaustiveness**: every match must cover all cases; add `_:` if not covering all variants explicitly
- **`$self()` only inside struct bodies**: using it elsewhere is invalid
- **`&&` capture count must match**: when `: |...|` is present, every capturable sub-condition must have a slot — use `_` to discard; mismatch is a compile error
- **`&&` vs `and`**: both are short-circuit boolean AND; `&&` additionally permits binding introduction per clause in `if` conditions
- **Module-level mutable globals**: require `mut`, e.g. `mut _state: usize = 0`
- **`!` is boolean not, `~` is bitwise not**: `if !found { ... }` — never write `not found`
