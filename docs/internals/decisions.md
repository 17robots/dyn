# Settled design decisions

- Compiler hosting and generated-code targets are separate support claims. See
  [releasing](release.md) for the supported scope.
- SDK archives contain the compiler, standard-library sources and runtime objects.
  Current Linux packages require external LLVM shared libraries.
- The compiler's handwritten parser (`src/parser.c`) defines Dyn syntax.
  `tree-sitter-dyn` serves editor highlighting and must accept the same syntax;
  editor packages pin its revision in `dyn-editors`.
- Directory builds output directory basename into command working directory; `--output`
  overrides. Existing output is atomically replaced without embedded compiler marker.
- Debug default. SDK ships standard-library source plus prebuilt platform runtime objects.
- C bootstrap uses strict C11 and compiles one object per source file, in parallel.
- Linux release builds use the LLVM version pinned in
  `.github/workflows/c-compiler.yml`.
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
