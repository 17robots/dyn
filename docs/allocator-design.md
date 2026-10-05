# Primitive allocator design and implementation

Dyn now has an experimental `Allocator` primitive and typed allocation builtins
available in SDK preview 16. This document records the agreed design, initial
implementation evidence, and limits. See the [migration guide](migrations/0.1.0-preview.16.md)
for upgrading from earlier SDKs.

## Agreed direction

The user selected allocation-only handles initially, typed fallible results with
`value`, `error`, and `ok` fields, compile-time-known callback functions, and named
error categories. This supersedes the earlier decision to postpone typed
allocation support. Fixed arenas remain the default recommendation; growth must
be selected explicitly. There is no GC, ARC, borrow checker, implicit allocator,
or asynchronous framework.

An allocator handle borrows mutable implementation state. Copying the handle
shares that state and does not copy an arena, transfer ownership, or allocate
memory. The current representation is two target-sized pointers: context and
allocation callback. One callback does not need a separate operations table.
Construction fixes the callback; ordinary assignment can replace an entire handle.

Any implementation can provide a compatible function. The compiler does not
require inheritance, a trait, or a recognized arena type. Stateful implementations
must keep their context at a stable address while handles can be used. Stateless
implementations may pass `nil` context.

## Application interface

```dyn
use "std/mem"

struct Particle { x: f32, y: f32 }

fn main() {
  storage: [16 * mem.KiB]u8
  arena := mem.arena_from_buffer(storage[..])
  output := mem.arena_allocator(&arena)

  result := #alloc_slice(Particle, output, 128)
  if !result.ok {
    if result.error == AllocError.Capacity {
      #panic("particle budget exhausted")
    }
    #panic("particle allocation failed")
  }
  particles := result.value
  particles[0].x = 1.0

  // The handle remains usable after reset. Earlier payloads do not.
  mem.arena_reset(&arena)
  next := #alloc_or_panic(Particle, output)
  next.y = 2.0
}
```

The builtin families are:

| Operation | Success value | Failure policy |
| --- | --- | --- |
| `#alloc_or_panic(T, output)` | `*T` | Panic |
| `#alloc(T, output)` | `#AllocResult(*T)` | Return result |
| `#alloc_slice_or_panic(T, output, count)` | `[]T` | Panic |
| `#alloc_slice(T, output, count)` | `#AllocResult([]T)` | Return result |

Each operation also has an uninitialized form: `#alloc_uninit`,
`#alloc_uninit_or_panic`, `#alloc_slice_uninit`, and `#alloc_slice_uninit_or_panic`. Ordinary allocation zeroes all
payload bytes. Uninitialized allocation makes no initialization guarantee; an
implementation may still return zeroed storage. Struct field default expressions
are not evaluated by these builtins. Allocate and then assign an initializer if
those defaults are required.

`#AllocResult(*T)` and `#AllocResult([]T)` name compiler-supported result types;
this does not introduce general user-defined generics. Their fields are `value`,
`error: AllocError`, and `ok: bool`. Failure returns a nil pointer or empty slice.
Named result types can appear in parameters, return types, aliases, and storage.

The builtins evaluate the allocator and count once, in that order. A slice count
must be `usize` or an integer literal accepted as `usize`. The compiler supplies
element size and alignment and checks multiplication before invoking the callback.
An element type must have a nonzero, known storage size.

A zero-count slice succeeds with an empty value without calling the callback,
provided the handle is initialized. An uninitialized handle returns
`AllocError.InvalidState`, even for zero-count requests. Panic forms use the same
failure paths and the existing panic/defer machinery.

## Implementation callback

The construction builtin accepts a context pointer and a known function address:

```dyn
#allocator(context, &allocate)
```

The callback signature is:

```dyn
fn allocate(context: rawptr, size: usize, alignment: usize,
            error: *AllocError) rawptr
```

The builtin initializes `error` to `AllocError.None`. The callback returns suitably
aligned storage for at least `size` bytes, or sets an error and returns nil. The
callback receives only nonzero, overflow-checked byte requests. It must not retain
the temporary error pointer. Initialization belongs to the builtin, so callbacks
need not zero returned bytes.

The error categories are `None`, `InvalidAlignment`, `Capacity`, `InvalidState`,
`Overflow`, and `System`. A callback returning nil without an error is normalized
to `InvalidState`. A callback reporting an error must not transfer ownership of a
new allocation: the builtin has no deallocation operation with which to recover
it. On failure, existing allocations must remain valid; diagnostic counters may
change. The callback remains trusted low-level code: the compiler cannot prove
that its pointer is aligned, large enough, or alive.

Runtime-selected function pointers cannot be supplied to `#allocator`. Runtime
selection between already-constructed allocator handles is allowed. No handle
fields are exposed to application code.

`mem.arena_allocator(&arena)` borrows a fixed arena and never grows it.
`mem.growing_allocator(&arena)` borrows a growing arena and obeys its configured
capacity limit. Both callbacks return uninitialized storage; default builtins
perform payload zeroing once. `_uninit` makes no initialization guarantee.

## Lifetime and resource operations

Reset, rewind, trim, and release remain operations on concrete owners. Handles
provide no individual deallocation, implicit heap fallback, synchronization,
automatic destruction, or reference counting. The descriptor must remain valid
for calls through a handle; payload validity follows the underlying allocator's
lifetime rules.

Direct construction with a pointer to local state participates in local-escape
diagnostics. The standard fixed-arena adapter preserves provenance for the
existing straight-line reset/rewind-to-zero checks. Reset invalidates payloads,
not the allocator handle. General wrapper functions and custom callbacks remain
outside that narrow analysis. These checks do not establish lifetime safety.

## Compiler integration

The implementation changes the grammar, AST type representation and layout,
semantic checking, IR type lowering, LLVM emission, reflection, query output,
editor builtin help and result-field completion, and the std arena adapters.
`Allocator` and allocation results are native Dyn values, not supported C ABI
values. Foreign code should exchange explicit pointers through an adapter.

Reflection adds `TypeKind.AllocationHandle` and `TypeKind.AllocationResult`.
Allocation result metadata includes its three fields. The corresponding
`std/reflect.Kind` categories are available. Debug information currently records
the primitive aggregate sizes but does not expose their internal member layout.

The compiler emits an ordinary callback invocation with the existing panic-unwind
handling. With a visible implementation, optimization can replace indirect calls
with direct calls or inline them. An immutable callback does not guarantee that
its identity is visible at every call site. Payload access afterward uses ordinary
pointers and slices and does not dispatch through the allocator.

## Validation and performance scope

`tests/allocator-builtins.py` covers custom and standard adapters, handle copying,
typed result returns across modules, alignment, zeroing and uninitialized storage,
zero counts, multiplication overflow, exhaustion preserving prior content,
invalid handles, malformed callback results, single count evaluation, reset/reuse,
reflection and query metadata, negative syntax/type/lifetime cases, and panic forms.
Runtime tests run in debug and release on Linux. Portable callback fixtures also
compile to objects for x86-64 Linux, AArch64 Linux, AArch64 macOS, x86-64 Windows,
and wasm32 WASI. Object compilation is not native execution or ABI qualification.

The reproducible local dispatch experiment is in
`tools/benchmark-allocator.py`; generated source modules, the compiler fingerprint,
and measurements are written under `build/allocator-benchmark/`. Run it with
`DYN=/path/to/dyn python3 tools/benchmark-allocator.py`.
It compares direct arena allocation, a locally constructed handle, and an imported
allocation wrapper, with and without link-time optimization. It measures a tiny
repeated-allocation workload, not application performance. Build timings between
these variants do not measure compiler slowdown against the previous compiler.

Current std consumers include `strings.clone_alloc`, `strings.join_alloc`, and
`ini.parse`. Concrete arena operations retain rollback where it is useful.
Wrapper-aware lifetime analysis and individually reclaimable generic allocation
are outside this design. Native non-Linux execution remains release work. `grammar.lock.json` pins
the grammar change; merge the upstream grammar PR before this compiler PR. See [memory API direction](memory-api-direction.md).

## Recorded local results

The initial allocator validation passed 23 checks. The expanded follow-up report
is [memory-readiness.json](validation/memory-readiness.json), recording the compiler
SHA-256 and 34 focused check results. The existing
six viability applications pass in debug and release; the new documentation
example brings the executable documentation total to ten programs. These are
focused checks rather than a complete release qualification.

For the recorded 1,280,000-allocation experiment, median elapsed milliseconds
across seven measured runs (after one warmup) were:

| Build | Direct arena | Local handle | Imported wrapper |
| --- | ---: | ---: | ---: |
| Release with LTO | 3.353 | 2.762 | 2.725 |
| Release without LTO | 4.829 | 8.976 | 12.136 |

The paths use the same arena storage strategy and default zeroing, but different
wrapper/error-handling code gives the optimizer different opportunities. These
numbers do not show that abstraction is inherently faster, or predict whole-app
performance. The experiment does show a material cost when dispatch and wrapper
calls survive optimization. Keep direct arena operations available for measured
hot paths. Results include neither a before/after compiler-time benchmark nor
native execution on other operating systems.
