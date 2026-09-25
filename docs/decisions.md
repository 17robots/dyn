# Settled design decisions

- Compiler hosting and generated-code targets are separate support claims. See
  [release readiness](release/readiness.md) for the supported scope.
- SDK archives contain the compiler, standard-library sources and runtime objects.
  Current Linux packages require external LLVM and Tree-sitter shared libraries.
- `tree-sitter-dyn/grammar.js` is grammar source of truth; editor copies are generated.
- Directory builds output directory basename into command working directory; `--output`
  overrides. Existing output is atomically replaced without embedded compiler marker.
- Debug default. SDK ships standard-library source plus prebuilt platform runtime objects.
- C bootstrap uses strict C11, unity default, and per-file CI validation.
- Release builds use LLVM 19 and Tree-sitter 0.25.8. See
  [toolchain](toolchain.md) and [distribution](release/distribution.md).
- Executable builds use a content-keyed, artifact-verifying sidecar cache; `--no-cache` bypasses it.
  Source diagnostics use byte spans internally and 1-based Unicode
  columns when rendered.
- One declaration namespace per module. Fields and enum variants have scoped namespaces.
- Duplicate canonical imports under different aliases warn; identical alias collides.
- AST is data-oriented, ID-based, arena-backed, span-preserving, and trivia-free.
- Successful `check` prints `ok`; diagnostics use stderr. Tagged release builds
  embed their version; ordinary development builds default to `0.1.0-dev`.
- `dyn help` lists the implemented commands. Declaration lookup and semantic
  project queries have distinct contracts; see [preview tools](preview-tools.md).
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
performance checks for the behavior being changed. The current requirements live
in [release readiness](release/readiness.md), not a second package roadmap.
