# Type parameters design

Status: phase 1 is implemented: generic functions, std phase 1, and
arena-only allocation replacing `Allocator` and the `#alloc*` builtins.
Phase 2 (generic structs) waits for measurements. See [Implementation status](#implementation-status).

Dyn gains one small feature: functions, and later structs, may take types as
parameters. The goal is to remove repeated per-type code and casts through
`*u8`/`rawptr` without adding a type-level language. The model is Go's
simplicity budget, Odin's `$T` syntax, and the way Ryan Fleury's code actually
uses generic helpers (`Min`, `Max`, `Clamp`, `Swap`, `push_array`): small,
unconstrained, and type-explicit when the type cannot be inferred.

## Rules in one paragraph

A parameter written `$T: type` takes a type argument at the call. A parameter
type containing `$T` (as in `a: $T`, `p: *$T` or `s: []$T`) declares `T`
and infers it from that argument. Elsewhere in the
declaration and body, `T` is an ordinary type name. Each distinct set of type
arguments produces one instance. The compiler checks every instance's body as
ordinary code; a body that is invalid for a type is an error at the call that
created the instance. There are no constraints, traits, interfaces, operator
overloading, specialization, or compile-time execution.

## Goals

- Replace the eight `#alloc*` builtins with std functions.
- Give std one generic version of slice helpers that are `[]u8`-only today
  (`copy`, `fill`, `zero`, `equal`, `reverse`) and of `min`, `max`, `clamp`,
  `swap`, `narrow`.
- Give applications typed arena pushes (`mem.push(Node, &arena)`), removing
  most pointer casts at allocation sites. DNA has about 50.
- Later, and only after measurement: generic structs for `List`, `Map`,
  `Rng1` and `Vec2`.

## Non-goals

These are permanent, not deferred. A proposal to add one requires a new
language decision, not an extension of this design.

- Constraints of any kind: traits, interfaces, concepts, type sets, user-written
  predicates.
- Operator overloading. Operators keep their fixed built-in meaning.
- Specialization: no different body for a particular type, and no overloading
  by parameter type.
- Generic methods, generic enums, generic unions, and generic type aliases.
- Value parameters (`$N: usize`) and compile-time function execution.
- Higher-kinded parameters (a parameter that is itself a generic type).
- Inferring the type parameters of a struct literal.

## Syntax

### Functions

```dyn
// Explicit type argument: the type is the first thing a reader sees.
pub fn push($T: type, arena: *Arena) *T {
  return #cast(*T) arena_push_or_panic(arena, #sizeof(T), #alignof(T))
}

pub fn push_array($T: type, arena: *Arena, count: usize) []T {
  bytes := arena_push_or_panic(arena, count * #sizeof(T), #alignof(T))
  return (#cast(*T) bytes)[..count]
}

// Inferred type argument: T comes from the arguments.
pub fn min(a, b: $T) T {
  if a < b { return a }
  return b
}

pub fn swap(a, b: *$T) {
  t := a.*
  a.* = b.*
  b.* = t
}

pub fn zero(value: *$T) {
  empty: T
  value.* = empty
}

pub fn copy(destination: []$T, source: []const T) usize {
  count := min(#len(destination), #len(source))
  for i in 0..count {
    destination[i] = source[i]
  }
  return count
}
```

Calls:

```dyn
node := mem.push(Node, &arena)
cells := mem.push_array(Cell, &arena, rows * cols)
low := min(width, height)
swap(&left, &right)
zero(&state.diagnostics)
```

Grammar additions:

- `$T: type` as a parameter. It may appear anywhere in the list; by
  convention it comes first.
- `$T` inside a parameter type, introducing `T`. Each name is introduced with
  `$` once; later uses, including within the same parameter list, use plain
  `T`.
- A type used as a call argument. This already parses for `#sizeof(T)`; it
  becomes valid only in a `$T: type` parameter position.

### Inference

Inference is matching only. Each argument's type is matched against its
parameter's type pattern, left to right. A parameter whose type contains no
`$` places no requirement on inference, but its argument is still checked
against the resulting type. Untyped integer and float literals take their default type
only after every other argument has been matched. So `min(x, 1)` with `x: u32`
instantiates `min(u32)`. Conflicts are errors:

```
error: T is both u32 and i64 in this call
  --> layout.dyn:40  min(width, offset)
  --> std/num/num.dyn:12  pub fn min(a, b: $T) T
```

No unification beyond this, no inference from the return type, and no
implicit conversion to make inference succeed (a `u32` argument does not widen
to match an `i64` one). Add a cast at the call.

### Structs (phase 2)

```dyn
pub struct List($T) {
  items: []T,
  count: usize,
}

names: List([]const u8) = {}
```

The parser already reserves `Name(T){...}`. Type arguments are always
explicit. Struct literals are written with the full type, `List(i32){}`, or as
`{}` where the target type is known. Recursive self-instantiation is limited to
the same arguments (`next: *List(T)`), which rules out unbounded instance
growth.

## Checking

### Instances, not templates of text

The compiler type-checks a generic declaration's signature once. It checks the
body once per instance, after substituting the concrete types. There is no
separate check of the body for "all T". This matches C macros and Odin, and it
is what keeps constraints unnecessary.

To keep error reporting simple, errors inside an instance print a short
instantiation trace, with the call that caused the instance first:

```
error: `<` is not defined for Rect
  --> ui.dyn:88  low := min(a, b)          T = Rect
  --> std/num/num.dyn:13  if a < b { return a }
```

At most four trace lines are printed. Nested instantiations beyond that are
summarized as `(N more)`.

### Limits

- Instance depth: 32. Exceeding it is an error naming the cycle.
- An instance's type arguments must be complete, concrete types: no `rawptr`
  inference from `nil`, no untyped constants after defaulting.
- `#sizeof(T)` inside a generic body is a constant per instance, as today.
- `#typeof(T)` works as for any type.
- Address-of a generic function (`&min`) requires explicit arguments, written
  `&min(i32)`, and produces an ordinary function pointer.

### Exports and visibility

A generic function is visible under the normal `pub` rules. Callers need its
signature, not its body; the body is checked and emitted with the declaring
module (see below).

## Implementation

The compiler budget is about 1,500 new lines across sema, codegen, caching and
the language server. If the prototype grows past 2,500, stop and simplify the
design rather than the code.

1. **Grammar.** `$identifier` in parameter types, `type` as a parameter kind,
   type arguments in struct types (phase 2). Editor queries highlight `$T`.
2. **Lowering.** Generic declarations stay in the AST unchanged, marked
   generic. Lowering, analysis and code generation skip them until they are
   instantiated.
3. **Instantiation.** At each call, sema resolves the type arguments, looks up
   `(declaration, argument type ids)` in a hash table, and creates the
   instance on first use: a substituted copy of the function's typed form,
   checked like a normal function. The table is per program, so each instance
   is checked once regardless of call count.
4. **Naming.** Instance symbols are `<declaration symbol>__g<hash of type ids>`.
   Debug info shows the readable name, `min(u32)`.
5. **Chunks and the cache.** An instance is emitted in the chunk of the module
   that declares the generic, using a stable order. Its owning chunk is
   determined by the declaration, so a body edit to `std/num` rebuilds only
   that chunk; a call site never compiles a private copy. The set of instances
   becomes part of the owner chunk's key, so adding a new instance rebuilds
   only that chunk. Generic signatures join the program's interface hash like
   any other signature. Generic bodies do not, so editing one rebuilds only
   its owner chunk, as for ordinary functions. Callers reference instances by
   symbol and stay cached.
6. **Release builds.** Instances are ordinary functions to ThinLTO, which
   inlines the small ones across chunks.
7. **Language server.** Hover shows the instance (`min(u32)`). Go to
   definition goes to the generic declaration. Completion offers `T` within the
   body.

### Compile-time budget

Measured with `tools/generate-scale.py` plus a variant that uses generic std
helpers at the same density as raddbg's `Min`/`Max` (about one call every 400
lines):

- `dyn check` on the 500k-line project: no more than 5% slower than preview 18.
- Debug build of DNA: no more than 5% slower.
- One-line body edit in DNA: unchanged (0.43 s).

If the prototype misses these numbers, generics do not ship.

## What it replaces

### Builtins (phase 1)

Allocation is arena-only. `Allocator`, `#allocator`, `#AllocResult`,
`AllocError` and all eight `#alloc*` builtins are removed; nothing replaces
them in the compiler. Typed allocation is ordinary std code:

| Today | After |
| --- | --- |
| `#alloc_or_panic(T, a)` | `mem.push(T, &arena)` |
| `#alloc_slice_or_panic(T, a, n)` | `mem.push_array(T, &arena, n)` |
| `#alloc_slice_uninit_or_panic(u8, a, n)` | `mem.push_bytes_uninit(&arena, n)` |
| `#alloc(T, a)` and other recoverable forms | `mem.arena_push*`, then check `.ok` |

Pushes zero by default. Uninitialized memory is only offered as bytes, which
covers the cases that need it: file reads, text, and vertex data that is
overwritten right away. Std functions that produced output through an
`Allocator` (`strings.clone_alloc`, `strings.join_alloc`, `ini.parse`) take
`*mem.Arena`.

### Std (phase 1)

- `math`: `min`, `max`, `clamp`, `abs`, `narrow(T, x)` (panics if the value
  does not fit; the checked counterpart of `#cast`). These replace the
  `_i64`/`_u64` versions.
- `mem`: `push`, `push_array`, `push_bytes_uninit`, `zero`, `swap`, `copy`,
  `move`, `fill`, `equal`.
- `sort`: `sort` (insertion sort below 16 elements, otherwise a heap sort;
  elements must support `<`) and `search`, replacing the `i64`/`u64` versions.
- `slice`: `reverse`, `index_of`, `contains`.

The `[]u8`-only versions of `copy`, `fill`, `zero` and `equal` are replaced,
not kept alongside. `[]u8` calls keep working because `T` is inferred as `u8`.

### Std (phase 2, only after phase 1 ships and is measured)

- `List($T)`: an arena-backed array that grows by copying.
- `Map($K, $V)`: fixed slot count, chained, arena-backed, keyed by any type
  with `==`. Requires a hash function chosen per key type; phase 2 must settle
  that without adding constraints (likely `hash: fn(*const K) u64` as a field).
- `Rng1($T)`, `Vec2($T)`: only if DNA's geometry work shows the concrete `f32`
  versions are not enough.

## Phases

1. Generic functions, std phase 1, removal of the `#alloc*` builtins with a
   migration note. DNA migrates arena pushes and `mem.zero` sites.
2. Measure in DNA and std for one release.
3. Generic structs and std phase 2, if phase 1 met the budget and real code
   asks for containers.

## Tests

- Positive: each std helper over integer, float, pointer, struct and slice
  types; explicit and inferred calls; instances shared across modules; one
  instance emitted once.
- Negative: conflicting inference, missing type argument, `$` on a non-parameter
  position, an operator invalid for the instance type (error points at the
  call and shows the trace), depth limit, `&min` without type arguments.
- Cache: editing a generic body rebuilds its chunk and keeps unrelated chunks;
  adding the first `min(f32)` call rebuilds the owner chunk only.
- Grammar: `tests/grammar-feature-errors` covers each rejected form in the
  non-goals list.

## Implementation status

Done:

- Grammar: `$T` as a type and as a `$T: type` parameter; `type_argument`
  call arguments for types that do not parse as expressions (`*T`, `[]T`,
  primitives). A plain name such as `Node` stays a name expression, and a
  generic call resolves it as a type.
- Instances are created during checking. Each instance's body is lowered
  again from the generic's syntax tree with its type parameters bound, and
  then checked like any function. Syntax trees outlive analysis, so no AST
  cloning is needed.
- Symbols are `<name>__g<hash>`, where the hash covers the formatted type
  arguments, so names stay stable when unrelated code changes.
- Cache: instances are excluded from the program's interface hash. Each
  chunk's key includes a hash of the instances it emits, so a new instance
  rebuilds only its generic's chunk plus the caller's.
- Diagnostics: conflicting inference, missing inference, type/value argument
  mismatches, taking the address of a generic, depth limit 32, and an
  instantiation trace of up to four notes.
- Language server: hover on a generic shows its declared signature.
- Tests: `tests/generics.py`. `tools/generate-scale.py --helpers` measures
  instantiation cost.

Measured on a 500k-line generated project, interleaved runs, minimum of 15
(noise floor about ±3%):

| Comparison | AST | Check total |
| --- | --- | --- |
| Without generics: this change vs preview 18 source | +2.6% | +2.9% |
| 1,352 generic `min`/`max` calls vs the same as `i64` functions | +1.5% | +2.6% |

A full debug build of 100k lines was unchanged (+0.2%).

Phase 1 std and builtins (done):

- `Allocator`, `#allocator`, `#AllocResult`, `AllocError` and the eight
  `#alloc*` builtins are removed; allocation is arena-only. Migration:
  `docs/migrations/0.1.0-preview.19.md`.
- `std/mem`, `std/math`, `std/sort` and the new `std/slice` use type
  parameters as listed above.
- The lifetime checker treats `mem.push*` like the arena pushes, so use
  after `arena_reset` is still an error.
- Debugging: instances carry a readable debug name, so gdb backtraces and
  panic traces show `min(u32)`. Break on one with `break min(u32)`, or on every
  instance with a file and line.
- DNA: the six `#alloc*` sites and 27 byte-buffer casts around
  `arena_push_uninit_or_panic` moved to `mem.push`, `mem.push_array` and
  `mem.push_bytes_uninit`.

Not done:

- Hover on a call does not yet show the instance (`min(u32)`).
- `break min` does not match instances; gdb needs the full `min(u32)`.
- Instance lookup is a linear scan per call; replace it with a hash table if
  a program creates thousands of instances.
- Struct literals cannot zero an arbitrary `T` (`.{}` needs a struct type);
  use a declaration without initializer, `v: T`, which zeroes any type.

## Open questions

- Whether `type` should be a keyword or remain an identifier in parameter
  position. Proposed: contextual, valid only after `$T:`.
- Whether `&min(i32)` is needed at all in phase 1. Proposed: reject taking the
  address of a generic function until a caller needs it.
