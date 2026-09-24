# Dyn

Dyn is an explicit native systems-programming language under construction. The C bootstrap
compiler emits Linux x86-64/AArch64, Windows x86-64, and macOS AArch64 native code. It supports
typed values, checked arithmetic, scoped `if`/`else`, condition and infinite `for`
loops, `break`, `continue`, and branch-local `return`. Bare expressions are not statements.
Nominal and packed structs support field defaults, literals, nested field access/update, and
value-copy assignment.
General functions support typed parameters/results, forward calls, recursion, void call
statements, and struct values passed or returned by value.
Function pointers support `*fn(...) Result`, explicit `&function` addresses, indirect calls,
storage in locals/globals/structs, signature checking, and runtime nil guards.
Semantic AST lowers through validated, source-independent typed Dyn IR before LLVM.
Thin mutable/const pointers support `nil`, address, checked dereference, automatic struct-field
dereference, nested mutation, and equality.
Fixed arrays and `{data,len}` slices support literals, zero-fill, value copying, checked indexing,
exclusive ranges, `#len`, and value-binding `for-in` traversal.
Explicit pointer ranges such as `pointer[..length]` construct slices for OS-owned memory; thin
pointers still cannot be indexed as single values.
Nominal enums support tagged payloads and exhaustive `case` matching.
Lexical `defer` runs LIFO on block fallthrough, return, loop exit, and current-frame panic paths.
Deferred calls capture operands immediately; deferred blocks observe storage when cleanup runs.
Core builtins provide layout/reflection queries, length, explicit numeric/pointer casts, scalar
bitcasts, panic, and target-translated low-level syscalls without depending on the standard library.
Ordinary Dyn standard-library modules provide fixed-buffer memory allocation, descriptor I/O,
process/time queries, logging, and opt-in reflection metadata.

Build commands require `just`, Python 3, and Bash. Set configuration through
environment variables before the command.

```sh
just test
just sanitize-test
./build/dyn help
./build/dyn check compiler
./build/dyn build compiler --output build/dyn-demo
./build/dyn run compiler --quiet
./build/dyn-demo
```

- `compiler/`: C11 bootstrap compiler and minimal runtime
- `tree-sitter-dyn/`: canonical grammar and editor queries
- `zed-dyn/`: generated Zed grammar artifact and highlights
- `docs/`: architecture, semantics, decisions, unresolved design
- `compiler/std/`: ordinary Dyn standard-library source shipped with SDK
- `tests/`: parser/CLI/code-generation/runtime tests

Start with the practical [idiomatic Dyn guide](docs/idiomatic-dyn.md).
For agents and explicit memory-lifetime patterns, see [application-writing workflow](docs/agent-guide.md).
Design references: [language](docs/language.md), [memory](docs/memory.md),
[error values](docs/errors.md), [operation costs](docs/costs.md),
[standard-library ABI](docs/standard-library-abi.md), and
[compatibility/support](docs/stability.md). See the concise [package reference](docs/packages.md).
Projects may declare explicit local or vendored dependency roots. Dyn intentionally has no package
manager or registry.
# Build and SDK

Build C bootstrap compiler with `just`; use `just release` for the optimized
`build/dyn-release` compiler. Validate with `just quality-c`.
Self-hosting is deferred until the C toolchain and SDK release gates are reliable.
`PREFIX=/usr/local just install` installs the optimized `dyn`, target runtime objects, and standard
library. `just install-check` tests a relocated temporary SDK. Run benchmarks with
`CC=clang ./benchmarks/run.sh 15`.

Current release scope and acceptance criteria: [0.1 readiness](docs/release/readiness.md).
Experimental output targets are not a claim that the compiler runs natively on those hosts.

Build rules live in `compiler/justfile`, `projects/justfile`, and
`tree-sitter-dyn/justfile`; root `just` delegates to them. Each component has its own
release/package entry points. See [component builds and releases](docs/build-layout.md).
