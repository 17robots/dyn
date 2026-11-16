# Settled design decisions

- Compiler hosting and generated-code targets are separate support claims. See
  [releasing](release.md) for the supported scope.
- SDK archives contain the compiler, standard-library sources and runtime objects.
  Packages bundle no LLVM, LLD, or C++ libraries.
- The compiler's handwritten parser (`src/parser.c`) defines Dyn syntax.
  `tree-sitter-dyn` serves editor highlighting and must accept the same syntax;
  editor packages pin its revision in `dyn-editors`.
- Directory builds output directory basename into command working directory; `--output`
  overrides. Existing output is atomically replaced without embedded compiler marker.
- Debug default. SDK ships standard-library source plus prebuilt platform runtime objects.
- C bootstrap uses strict C11 and compiles one object per source file, in parallel.
- Independent emission is the only backend in debug and release. External LLVM
  tools serve only as optional format-validation oracles in tests.
- Executable builds use a content-keyed, artifact-verifying sidecar cache; `--no-cache` bypasses it.
  Source diagnostics use byte spans internally and 1-based Unicode
  columns when rendered.
- One declaration namespace per module. Fields and enum variants have scoped namespaces.
- Duplicate canonical imports under different aliases warn; identical alias collides.
- AST is data-oriented, ID-based, arena-backed, span-preserving, and trivia-free.
- Successful `check` prints `ok`; diagnostics use stderr. Tagged release builds
  embed their version; ordinary development builds default to `0.1.0-dev`.
- `dyn help` lists the implemented commands. Declaration lookup and semantic
  project queries have distinct contracts; see [tools](../guide/tools.md).
- Linux core owns `_start` and does not require libc in produced empty executable.
- Bare expressions are not statements. Function calls may stand alone as call statements.
- Functions support explicit void `return`.

## Change criteria

Keep allocation, storage ownership, errors and operation costs visible. Borrowed
pointers and slices do not extend backing-storage lifetime. Expected failure uses
ordinary values; panic is reserved for documented invariant failures or explicitly
infallible convenience forms.

Language and SDK additions should remove concrete caller complexity. Prefer a
small module interface that owns useful behavior over aliases or forwarding layers.
Before adding syntax, check whether existing constructs express the operation.
Require matching contracts and meaningful conformance, negative, integration or
performance checks for the behavior being changed.

Prefer explicit forms over inferred ones. `Enum.Variant` is always written in
full, there are no local type aliases, and types are inferred only from call
arguments. Make the zero value of every type useful, and handle errors by
recording them in state and checking once.

## Ledger, 2026-11

Decisions the project owner approved, with dates. A language feature that is not
listed here or in the guide was never approved and is a candidate for removal.

Goal (2026-11-15): Dyn is simple, clean, fast and fun to write. It has only the
features real code needs and a large standard library. Std, core and heap are
ordinary Dyn code: the compiler never treats code differently by its name or path.

- 2026-11-15: enums with payloads, `distinct type`, `packed struct`, `#reverse`,
  generic structs and generic enums stay. `#assert` stays for compile-time checks;
  run-time `assert` is a std function built on `#panic`.
- 2026-11-15: no `var`/`const` split, no immutability by default, parameters are
  mutable copies, `*const` and `[]const` are shallow.
- 2026-11-15: errors are state on the object (`x.failed`, `x.failure`), checked once
  where it matters. No error values checked after every call, no errno, no try/catch.
- 2026-11-15: arenas are the memory model, with a short interface and a replaceable
  block source. Std splits into core (no OS, no memory source), heap and std.
- 2026-11-15: the builtin list holds only what the compiler must provide.
- 2026-11-16: overflow checks are opt-in (`--check-overflow`) and also check SDK std,
  which must pass with them on.
- 2026-11-16: `&T{...}` is allowed; `x & M` and unsigned `x >> k` narrow without a cast.
- 2026-11-16: `#sqrt`, `#floor`, `#ceil`, `#trunc`, `#round`, `#fma`: builtins are fine
  when they map to a hardware instruction.
- 2026-11-16: `#init(p)` makes a fresh value of any type.
- 2026-11-16: format templates are library code; structs print at run time; `dyn vet`
  checks literal templates.
- 2026-11-16: handles are plain values, closed once; `dyn vet` catches a copy closed twice.
- 2026-11-16: removed: labeled loops, `for *const`, `#load`, `#instance`, `#offset`,
  `#offsetof` (field offsets come from `TypeMember.offset`), `#max`/`#min`,
  exhaustiveness proved by integer ranges, panic unwinding through caller frames
  (`panic.set_handler` stays).
- 2026-11-16: added: `#step(range, n)`; target-typed arithmetic (an expression
  computes in its widest type, including the type it is stored into); signed and
  unsigned comparison compares values correctly; `x % n` narrows; generic inference
  uses the ordinary conversion rules. Pointer `<` stays.
- 2026-11-16: not added: a variable in the `for` header, `#bitfield`. Deferred: `#soa`.
