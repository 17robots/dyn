# Dyn language reference

This page defines the language as the compiler implements it. For how to write
Dyn well, read [idiomatic Dyn](idiomatic-dyn.md) first.

## Modules and entry points

A directory is one module; its immediate `.dyn` files share one namespace. Files are
sorted canonically for deterministic processing. `dyn build DIR` requires `DIR/main.dyn`
containing exactly `fn main()` (optional `pub`, no arguments or return value). `dyn check`
also accepts library modules.

Compiler resource contract currently limits one source file to 64 MiB, one module to 4096 source
files, one merged module to 256 MiB, and syntax nesting to 1024 levels. Exceeding a limit is a diagnostic, not an allocation
failure or compiler crash.

`use "std/terminal"` binds `terminal`; `use "std/io" raw_io` binds `raw_io`; `use "std/io" io,
"std/fs" fs` imports several modules in one `use`. `as` is invalid. Relative
imports use `./` or `../` but cannot escape project root. Other paths resolve from project
root; `std/` and `vendor/` resolve only inside the SDK. `DYN_SDK` may name an SDK root containing
`std/` and `vendor/` collections, which is useful for SDK development and alternate installations.
Import paths are canonicalized. Declarations across
same module see each other regardless of file/source order. `pub` controls imported access.
Imported functions and types must currently be module-qualified; imports never inject names into
the local namespace. Qualified enum construction and patterns use `module.Enum.Variant`.

Top-level variable syntax also declares globals. Globals are zero-initialized before optional
runtime initialization and may be mutated; imported globals require `pub` and qualified access.
Constants require compile-time expressions and cannot be assigned after declaration.
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

A parameter written `$T: type` takes a type argument at the call, as in
`mem.push(Node, &arena)`. A parameter type containing `$T`, such as `a: $T`, `p: *$T` or
`s: []$T`, declares `T` and infers it from that argument, as in `sort.sort(values)`. Elsewhere in
the declaration and body, `T` is an ordinary type name. Write `$T` once; later parameters write
`T` and must match exactly, with no implicit widening:

```dyn
fn max(a: $T, b: T) T {
  if a > b { return a }
  return b
}
```

`max(x, y)` with `x: i32` and `y: i64` is an error (`T is both i32 and i64`); cast one argument. Each distinct set of type arguments makes
one instance, and the compiler checks each instance's body as ordinary code: a body that is invalid
for a type is an error at the call that created the instance. There are no constraints, traits,
interfaces, operator overloading or compile-time execution, and types are inferred only from
arguments, never from the expected result. Structs, enums and unions never take type parameters. The
[generics design](../internals/generics-design.md) records the rules and what is deliberately left
out.

## Values and types

A string is a `[]const u8`: pointer and byte count, no trailing zero. The type does not
guarantee UTF-8. Source files and literal text are UTF-8, but `\x` escapes can write any byte,
and bytes read from files, sockets, or the OS arrive unchecked. Text APIs that require UTF-8
say so and validate; check external input with `utf8.valid` from `std/unicode/utf8` before
treating it as text. `const` prevents writes through this view only: another `[]u8` alias of the
same memory can still change the bytes. Character literals contain Unicode scalar values, defaulting to `u8` through 255 and
`u32` above it; expected `u8`, `u16`, or `u32` may apply when value fits.

`distinct`, `packed` and `is` are keywords only where they begin `distinct type`, `packed
struct` and a `case` type pattern; elsewhere they are ordinary names. `type` is always reserved.

`type` creates module-level transparent aliases; aliases may be forward-referenced and
alias cycles fail. There are no local aliases; declare them at module scope.
`distinct type Name = T` creates a nominal numeric type with `T`'s representation. Values cross
the distinct boundary only through explicit `#cast`; same-type arithmetic preserves the distinct
type. Structs/enums remain nominal. Struct field defaults must be
compile-time expressions and cannot reference instance fields. Field defaults
apply only to struct literals: storage zeroed any other way, such as by
`mem.push`, holds zeros. Design structs so that zero is a useful value.

Implicit numeric conversion is allowed only when destination represents every source-type
value exactly. Constants adapt when their specific value fits, and a literal that does not fit
its context is a compile error, checked again for each type a generic function is called with.
An integer literal in a float context is that float when it is exact (up to 2^24 for `f32`,
2^53 for `f64`), so `x * 2` works for any numeric `T`. Integers use checked
arithmetic in debug and release. Floats use IEEE-754. Expression evaluation is left-to-right.
Float literals accept trailing dots (`2.`); lexical lookahead keeps `2..3` an integer range.
Explicit primitive locals without initializers start at zero. Inferred locals require an
initializer. Local shadowing is forbidden: a local cannot reuse the name of a visible local or
parameter. A name becomes reusable after its block or loop ends, so sibling blocks and consecutive
loops may each declare `value`. Assignments copy values; compound assignments use
the same checked operators as ordinary expressions. An assignment evaluates its target (indexes,
pointer operands) before its value: in `a[i()] = f()`, `i()` runs first. A compound assignment
evaluates its target once, so `a[i()] += f()` calls `i()` once. Struct literal fields evaluate in
written order, not declaration order.

`if` and condition-form `for` require `bool`. Bare `for {}` is an infinite loop. `break` and
`continue` require an enclosing loop. Block locals are inaccessible after block exit. `for value in
collection` accepts arrays and slices, evaluates the collection once, and copies each element into
the loop-local binding. `for *value` binds a mutable pointer to each source element; mutable binding
rejects const slices and requires assignable arrays. `for *const value` binds a const pointer.
`for i in first..last` counts integers from `first` up to but excluding `last`; `..=` includes
`last`. Both bounds share one integer type, and a literal bound adapts to the other bound, so
`0..count` has `count`'s type. When both bounds are literals, `i` is `usize`, or `isize` if a
bound is negative, so `for i in 0..3 { values[i] }` indexes directly. Bounds evaluate once, first
bound first. An empty range such as `5..2` runs no iterations. `i` is a copy: assigning it does not change iteration, and pointer
bindings are rejected. Inclusive ranges may end at the type's maximum without overflow.
`for i in #reverse(first..last)` visits the same values from last to first: `#reverse(0..3)` gives
2, 1, 0 and `#reverse(1..=3)` gives 3, 2, 1. A descending range stays empty with or without
`#reverse`. `for value in #reverse(values)` and `for *value in #reverse(values)` visit array or
slice elements from last to first. `#reverse` is valid only as a `for` iterable and never wraps an
unsigned bound.
Loops may be labeled as `name: for`; `break: name` and `continue: name` target any active enclosing
loop with that label. Active labels cannot duplicate. Transfers run defers for every exited scope.

Struct field order determines layout. Packed structs preserve order, remove inter-field padding,
and have alignment 1 on current Linux x86-64 target. Construction zeroes every field, applies field
defaults in declaration order, then applies explicit literal members. `.{ ... }` requires expected
struct type. Struct assignment copies by value. Unknown/duplicate fields, duplicate declarations,
by-value recursion and aggregate comparison fail. Empty structs have size and alignment 1 so arrays
have stable element stride and distinct elements have distinct addresses.

Functions may accept and return primitive or struct values. Arguments evaluate left-to-right and
must match declared parameter count/types, subject to normal lossless conversions. Non-void
functions must return on every reachable exit. Calling a non-void function as a statement is an
error; use `_ = call()` to discard its result. Forward calls and direct recursion are supported.

Enums are nominal. Tags default to `u32` or use an explicit integer backing type, as in
`enum(u8) Op`. Variants receive declaration-order tags starting at 0. A plain enum may give
variants explicit values: `enum(u8) Op { Add = 1, Sub, Halt = 0xFF }`. Values are integer
literals that must fit the tag type, and a variant without one is the previous value plus one.
Duplicate values are errors. Enums with payloads keep implicit values. Every enum needs a
variant whose value is 0, so zeroed storage (`x: Color`, omitted struct fields, `mem.push`)
always holds a valid variant. An exhaustive `case` that meets a tag matching no variant, which
only foreign code or raw pointer writes can produce, panics with `enum.tag.ok`.
Payload variants hold one typed value and use `Enum.Variant(payload)` construction. Plain
variants use `Enum.Variant`; the type is always written, never inferred from context. Plain
enums support equality only; payload enums are not comparable. Enum values copy by value.
`#cast(u8, op)` gives a plain enum's tag, and `#cast(Op, byte)` converts an integer back,
panicking when the value is not one of the variants.
Plain enums have the size/alignment of the backing integer. A payload enum is laid out as its tag,
padding to the maximum payload alignment, then storage large/aligned enough for the largest payload;
final size is rounded to the maximum of tag/payload alignment. This is the Dyn ABI, not an automatic
C enum/union ABI. Every tag value must fit the backing type.

Bit masks use distinct unsigned integer types, not special flag-enum syntax. Values explicitly
cast into the mask type; ordinary integer `|`, `&`, `^`, and `~` then preserve its nominal type.
Enums remain single-choice values.

Pointers are thin and zero-initialize to `nil`. `&value` requires assignable storage; `pointer.*`
dereferences it. Struct fields automatically dereference struct pointers. Dereference checks nil
and pointee alignment, then panics on failure. Pointer arithmetic and ordering are forbidden;
equality with compatible pointers or `nil` is allowed. Mutable pointers implicitly widen to
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

Pointers are thin. Dereference checks nil and alignment, but not lifetime or allocation
bounds. Pointer comparisons support only equality. Thin pointers cannot be indexed as single values,
but `pointer[start..end]` constructs a slice and requires an explicit end bound. Slices are `{data, len}` descriptors and are
never comparable. Fixed arrays copy by value; omitted literal elements zero-fill, including typed
`[]`. Array/slice indexing is bounds-checked. Indexes and slice bounds accept any integer type no wider than `usize`, as in C; a negative signed value fails the bounds check like any other out-of-range index. Use `#cast` for wider types, such as `i64` on 32-bit targets. Exclusive ranges support `[..]`, `[..end]`,
`[start..]`, and `[start..end]`, checking `start <= end <= len`. `#len` returns `usize`.
`rawptr` has no direct indexing or slicing. Cast it explicitly to `*T`, then use
the ordinary bounded pointer-slice form: `(#cast(*T, memory))[..count]`. No second
raw-pointer range construct is planned.
`rawptr` has native pointer size/alignment, zero-initializes to `nil`, and supports equality and
an implicit conversion from mutable typed pointers, and explicit casts to/from compatible typed
pointers or native-width integers. It has no pointee,
ownership, lifetime, arithmetic, indexing, or dereference operation.

## Control flow and cleanup

Each statement starts on its own line; two statements on one line are a syntax error. A block
with a single statement may stay on one line, as in `if done { return }`. `case` arms are not
separated by commas; each arm's body is a block:

```dyn
case kind {
  0 => { return "none" }
  1 => { return "one" }
  _ => { return "many" }
}
```

Every `case` is exhaustive or contains `_`; integer interval analysis may prove exhaustive
coverage. Patterns use literals/constants only. Arm order is irrelevant; duplicates,
overlaps, unreachable `_`, and redundant `_` fail. `Variant payload` copies its payload.
`Variant *payload` aliases payload storage and permits assignment or field mutation; it requires a
mutable assignable case subject. The alias exists only inside its arm.
Enum cases may be exhaustive by listing every variant. Integer cases may be exhaustive by covering
the whole representable interval. Because the set of Dyn types is open, an `any` type case always
requires `_`. Type patterns neither implicitly cast nor match aliases by spelling: they compare the
boxed concrete type identity and bind a copied value of that exact type.

`defer` runs at enclosing-block exit in LIFO order. Direct-call arguments evaluate at defer
site. Deferred blocks observe captured storage at execution. Deferred statements exclude
`return`, `break`, `continue`, declarations, and nested `defer`. Double panic aborts cleanup.

Panic runs active defers through caller frames. Cleanup uses fixed stack records and performs no
allocation. A panic raised by a defer aborts remaining cleanup. There is no recovery mechanism. A panic that
crosses foreign frames runs Dyn defers but skips cleanup in the C frames between them; see
[FFI](ffi.md).

## Numeric rules

Integer widths are fixed except `isize`/`usize`, which match the target pointer width. Signed values
use two's-complement representation. `+`, `-`, `*`, unary negation, and signed division overflow
panic at runtime and are rejected when overflowing at compile time. Division/remainder by zero
panic; the signed minimum divided by `-1` also panics. Shift counts must be nonnegative and less
than the left operand width. Right shift is arithmetic for signed and logical for unsigned values.
Bitwise operators require integers. For hashes, random number generators and other code that
wants modular arithmetic, `#wrap(expression)` makes the `+`, `-`, `*`, unary `-` and `<<`
written inside it wrap around instead of panicking. Division and shift counts stay checked, and
calls inside `#wrap` are not affected.

Untyped integer constants are evaluated exactly for the implemented constant-expression operators,
then adapted only when their value is representable in the expected type. Runtime implicit numeric
conversion is allowed only when every source-type value is exactly representable. `#cast` permits
intentional narrowing and uses destination-width two's-complement/modulo representation for integers;
float-to-integer conversion requires a finite in-range value. `#bitcast` preserves bits and requires
equal-sized scalar representations. Boolean/numeric conversion is never implicit.

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

Unlike C, bitwise operators bind tighter than comparisons: `flags & mask == 0` means
`(flags & mask) == 0`. Comparisons do not chain: `a < b < c` compares a `bool` with `c` and
fails to type-check.

## Builtins

The `#` prefix identifies a compiler intrinsic or module directive. It does not
mean that the operation runs at compile time. Allocation, I/O, formatting,
collections, and ordinary algorithms belong in libraries.

- Conversion: `#cast(Type, value)` and `#bitcast(Type, value)`.
- Layout and reflection: `#sizeof`, `#alignof`, `#offsetof`, and `#typeof`.
- Representation and arithmetic: `#len` and `#wrap`.
- Validation and termination: compile-time `#assert` and runtime `#panic`.
- Build input and OS boundary: `#load` and `#syscall`.
- Iteration: `#reverse`, valid only in a `for` iterable.
- Module directives: `#target` and `#link`, documented with platform and FFI rules.

Conversions require exactly two arguments, with the type first. The value may be
any expression and is evaluated exactly once. The closing parenthesis delimits
that expression: `#cast(i64, a + b)` converts the sum, while
`#cast(i64, a) + b` converts only `a`. Cast results accept ordinary postfix
operations, such as `#cast(*T, memory)[..count]`. The old `#cast(T) value` and
`#bitcast(T) value` forms are rejected; see the
[migration guide](../migrations/cast-syntax.md).


`#sizeof(type_or_value)` and `#alignof(type_or_value)` return `usize` constants without evaluating
value operands. `#len` accepts arrays and slices. `#cast(T, value)` performs explicit numeric conversion
or compatible pointer conversion; explicit integer-pointer casts serve OS ABI boundaries. Narrowing follows destination representation. `#bitcast(T, value)`
requires equal-sized compatible numeric representations or compatible pointer representations.
`#syscall(number, args...)` returns `isize` and accepts at most six integer/pointer arguments on
Linux x86-64. It does not depend on `std`.
`#offsetof(Type, field)` is a field's byte offset as a `usize` constant.
`#assert(condition, "message")` fails compilation when a constant condition is false.
`#load("file")` embeds a file's bytes as a `[]const u8`; the path is relative to the module directory and may not contain `..`.
`#wrap(expression)` is described under numeric rules.

`#panic(message)` accepts any `[]const u8` expression; messages need not be literals.

`#typeof(type_or_value)` returns compiler-provided `TypeInfo` without evaluating value operands.
It requires no standard-library import. Metadata includes stable name-derived ID, `TypeKind`, name, size, and
alignment. Only types passed to `#typeof` emit name metadata. Bare function names are accepted.
Struct fields, enum variants, and function arguments expose immutable name/type-ID descriptors;
recursive relationships use IDs rather than nested metadata.

## Removed/deferred syntax

No `inline`, `thread_local`, `as`, wrapping operators such as `+%` (use `#wrap`), `~=`, or C-style casts.
`#cast(T, value)` and `#bitcast(T, value)` are explicit. Unary `!` is bool-only;
unary `~` is integer-only. Comments do not nest; whitespace is insignificant; semicolons are
unsupported.

The parser also recognizes reserved syntax for editor recovery. Parsing alone
is not a supported-feature claim:

| Syntax | Compiler status |
| --- | --- |
| Struct literals with type arguments, such as `Box(i32){...}` | Rejected syntax in compiler and editors |
| Module-level transparent type alias | Supported |
| Local type alias inside a function | Reserved; diagnosed as unsupported |
| Enum declaration-order tags | Supported |
| Explicit enum values on plain enums | Supported |
| `.Variant` without the enum type | Not planned; write `Enum.Variant` |
| Several imports in one `use`, comma-separated | Supported |
| Optional import alias followed by a new global | Supported; alias stays on the import line |

`tests/grammar-feature-errors` checks the reserved forms. See
[toolchain and grammar provenance](tools.md) for generation/release checks.

## Build modes and syntax stability

Debug and release have identical language correctness semantics. Both retain checked arithmetic,
division, shifts, bounds, nil, and alignment checks unless proven redundant. Debug records function
frames for panic diagnostics. Release omits that tracing and enables backend optimization/internal
linkage; it may therefore show fewer diagnostic frames, never different valid results.

Core syntax is frozen for the current `0.1` release cycle. A syntax addition requires a language
decision, grammar/editor updates, positive and negative tests, and release notes. Library growth does
not justify new syntax when existing functions/types express the idea.
