# Settled design decisions

- First milestone is honest Linux x86-64 vertical slice; other targets follow.
- Developer build dependencies allowed. Users receive self-contained Go-like SDK archive.
- `tree-sitter-dyn/grammar.js` is grammar source of truth; editor copies are generated.
- Directory builds output directory basename into command working directory; `--output`
  overrides. Existing output is atomically replaced without embedded compiler marker.
- Debug default. SDK ships standard-library source plus prebuilt platform runtime objects.
- C bootstrap uses strict C11, unity default, and per-file CI validation.
- Tree-sitter runtime is pinned/vendored for release; LLVM build version will be pinned.
- Executable builds use a content-keyed, artifact-verifying sidecar cache; `--no-cache` bypasses it.
  Source diagnostics use byte spans internally and 1-based Unicode
  columns when rendered.
- One declaration namespace per module. Fields and enum variants have scoped namespaces.
- Duplicate canonical imports under different aliases warn; identical alias collides.
- AST is data-oriented, ID-based, arena-backed, span-preserving, and trivia-free.
- Successful `check` prints `ok`; diagnostics use stderr. Version is `0.1.0-dev`.
- Initial commands: `check`, `build`, `help`, `version`; future commands fail honestly.
- Linux core owns `_start` and does not require libc in produced empty executable.
- Bare expressions are not statements. Function calls may stand alone as call statements.
- Current executable subset adds explicit void `return`.
