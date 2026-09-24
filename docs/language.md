# Dyn language semantics

This document records normative decisions supplementing `PROMPT.md`.

## Modules and entry points

A directory is one module; its immediate `.dyn` files share one namespace. Files are
sorted canonically for deterministic processing. `dyn build DIR` requires `DIR/main.dyn`
containing exactly `fn main()` (optional `pub`, no arguments or return value). `dyn check`
also accepts library modules.

Compiler resource contract currently limits one source file to 64 MiB, one module to 4096 source
files, one merged module to 256 MiB, and syntax nesting to 1024 Tree-sitter tree levels. Exceeding a limit is a diagnostic, not an allocation
failure or compiler crash.

`use "std/terminal"` binds `terminal`; `use "std/io" raw_io` binds `raw_io`. `as` is invalid. Relative
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
Runtime initializers execute once before `main`, after every initializer they reference. Ordering
between otherwise independent globals is deterministic canonical module/source order but programs
must not use that order as synchronization or as an implicit dependency. Cycles are rejected.

Function pointer types use `*fn(ParamTypes) Result`; omitted result means `void`. Function
addresses require `&name`. Function pointers may be copied, stored in aggregates, and called with
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

## Values and types

Strings are immutable UTF-8 `[]const u8` values with pointer and byte count; no trailing
zero. Character literals contain Unicode scalar values, defaulting to `u8` through 255 and
`u32` above it; expected `u8`, `u16`, or `u32` may apply when value fits.

`type` creates module-level transparent aliases; aliases may be forward-referenced and
alias cycles fail. Local aliases are unsupported; declare them at module scope.
`distinct type Name = T` creates a nominal numeric type with `T`'s representation. Values cross
the distinct boundary only through explicit `#cast`; same-type arithmetic preserves the distinct
type. Structs/enums remain nominal. Enum
tags default to `u32`. Payload enums have no equality. Struct field defaults must be
compile-time expressions and cannot reference instance fields.

Implicit numeric conversion is allowed only when destination represents every source-type
value exactly. Constants adapt when their specific value fits. Integers use checked
arithmetic in debug and release. Floats use IEEE-754. Expression evaluation is left-to-right.
Float literals accept trailing dots (`2.`); lexical lookahead keeps `2..3` an integer range.
Explicit primitive locals without initializers start at zero. Inferred locals require an
initializer. Local shadowing is forbidden. Assignments copy values; compound assignments use
the same checked operators as ordinary expressions.

`if` and condition-form `for` require `bool`. Bare `for {}` is an infinite loop. `break` and
`continue` require an enclosing loop. Block locals are inaccessible after block exit. `for value in
collection` accepts arrays and slices, evaluates the collection once, and copies each element into
the loop-local binding. `for *value` binds a mutable pointer to each source element; mutable binding
rejects const slices and requires assignable arrays. `for *const value` binds a const pointer.
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

Enums are nominal. Tags default to `u32` or use an explicit integer backing type. Variants receive
declaration-order tags; explicit discriminants are unsupported. Payload variants hold one typed
value and use `Enum.Variant(payload)` construction. Plain variants use `Enum.Variant`. Plain enums
support equality only; payload enums are not comparable. Enum values copy by value.
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
while a mutable pointer stored in such a field still permits mutation of its own pointee. `rawptr`
is untyped storage and cannot be dereferenced; explicitly cast it to a typed pointer before access.

Pointers are thin. Dereference checks nil and alignment, but not lifetime or allocation
bounds. Pointer comparisons support only equality. Thin pointers cannot be indexed as single values,
but `pointer[start..end]` constructs a slice and requires an explicit end bound. Slices are `{data, len}` descriptors and are
never comparable. Fixed arrays copy by value; omitted literal elements zero-fill, including typed
`[]`. Array/slice indexing is bounds-checked. Exclusive ranges support `[..]`, `[..end]`,
`[start..]`, and `[start..end]`, checking `start <= end <= len`. `#len` returns `usize`.
`rawptr` has no direct indexing or slicing. Cast it explicitly to `*T`, then use
the ordinary bounded pointer-slice form: `(#cast(*T) memory)[..count]`. No second
raw-pointer range construct is planned.
`rawptr` has native pointer size/alignment, zero-initializes to `nil`, and supports equality and
explicit casts to/from compatible typed pointers or native-width integers. It has no pointee,
ownership, lifetime, arithmetic, indexing, or dereference operation.

## Control flow and cleanup

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
allocation. A panic raised by a defer aborts remaining cleanup. There is no recovery mechanism.

## Numeric rules

Integer widths are fixed except `isize`/`usize`, which match the target pointer width. Signed values
use two's-complement representation. `+`, `-`, `*`, unary negation, and signed division overflow
panic at runtime and are rejected when overflowing at compile time. Division/remainder by zero
panic; the signed minimum divided by `-1` also panics. Shift counts must be nonnegative and less
than the left operand width. Right shift is arithmetic for signed and logical for unsigned values.
Bitwise operators require integers. There are no implicit wrapping operators.

Untyped integer constants are evaluated exactly for the implemented constant-expression operators,
then adapted only when their value is representable in the expected type. Runtime implicit numeric
conversion is allowed only when every source-type value is exactly representable. `#cast` permits
intentional narrowing and uses destination-width two's-complement/modulo representation for integers;
float-to-integer conversion requires a finite in-range value. `#bitcast` preserves bits and requires
equal-sized scalar representations. Boolean/numeric conversion is never implicit.

Empty or partially specified fixed-array constants zero-fill omitted elements. Compiler work and IR
for an empty aggregate must remain bounded by written initializer count rather than storage size.

## Builtins

`#sizeof(type_or_value)` and `#alignof(type_or_value)` return `usize` constants without evaluating
value operands. `#len` accepts arrays and slices. `#cast(T)` performs explicit numeric conversion
or compatible pointer conversion; explicit integer-pointer casts serve OS ABI boundaries. Narrowing follows destination representation. `#bitcast(T)`
requires equal-sized compatible numeric representations or compatible pointer representations.
`#syscall(number, args...)` returns `isize` and accepts at most six integer/pointer arguments on
Linux x86-64. It does not depend on `std`.
Lossy-cast warnings are not wired into CLI warning controls yet.

`#panic(message)` accepts any `[]const u8` expression; messages need not be literals.

`#typeof(type_or_value)` returns compiler-provided `TypeInfo` without evaluating value operands.
It requires no standard-library import. Metadata includes stable name-derived ID, `TypeKind`, name, size, and
alignment. Only types passed to `#typeof` emit name metadata. Bare function names are accepted.
Struct fields, enum variants, and function arguments expose immutable name/type-ID descriptors;
recursive relationships use IDs rather than nested metadata.

## Removed/deferred syntax

No `inline`, `thread_local`, `as`, wrapping operators, `~=`, or C-style casts.
`#cast(T) value` and `#bitcast(T) value` are explicit. Unary `!` is bool-only;
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
| Explicit enum discriminants | Reserved; diagnosed as unsupported |
| Comment-separated import members/types | Supported |
| Optional import alias followed by a new global | Supported; alias stays on the import line |

`tests/grammar-feature-errors` checks the reserved forms. See
[toolchain and grammar provenance](toolchain.md) for generation/release checks.

## Build modes and syntax stability

Debug and release have identical language correctness semantics. Both retain checked arithmetic,
division, shifts, bounds, nil, and alignment checks unless proven redundant. Debug records function
frames for panic diagnostics. Release omits that tracing and enables LLVM optimization/internal
linkage; it may therefore show fewer diagnostic frames, never different valid results.

Core syntax is frozen for the current `0.1` release cycle. A syntax addition requires a language
decision, grammar/editor updates, positive and negative tests, and release notes. Library growth does
not justify new syntax when existing functions/types express the idea.
