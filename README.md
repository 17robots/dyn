# The Dyn Language

## Quick Commands
- Build CLI: `zig build`
- Run full test suite: `zig test src/backend_driver.zig`
- Check a program: `zig build run -- check path/to/main.dyn`
- Build executable: `zig build run -- build path/to/main.dyn -o out/app`
- Run program: `zig build run -- run path/to/main.dyn`
- Clean intermediates: `zig build run -- clean`

## Current Priorities (This Week)
- [ ] Implement full optional/error runtime semantics for `.?` and `.!` in IR + backend (non-pass-through behavior)
- [ ] Implement richer pointer type/value model with element-type-aware operations
- [ ] Define and implement memory/runtime model (heap/global pointer strategy, ownership/lifetime rules)

## Known Bugs
- Pointer/unwrap runtime model is still partial: `.?` and `.!` are semantically checked but do not yet have a distinct runtime representation in lowering/codegen.

## TODO
- Legend: `[x] done`, `[~] partial/in progress`, `[ ] not started`

### 1) Frontend Pipeline
- [x] Lexer
  - [x] Numeric/string/char tokenization
  - [x] Comments and trivia handling
  - [x] Error tokens and diagnostics integration
- [x] Parser
  - [x] Declarations, expressions, calls, control flow
  - [x] Postfix operators `.*`, `.?`, `.!`
  - [x] Aggregate/function/module syntax coverage
- [x] Source manager + spans
- [x] Diagnostics printing and formatting

### 2) Module System
- [x] Same-directory multi-file module grouping
- [x] `use "path/to/mod"` resolution semantics
- [x] Nested module import resolution
- [x] Import cycle detection
- [x] Deterministic module file scan ordering
- [x] Duplicate/conflicting module declaration diagnostics

### 3) Semantic Checker
- [x] Symbol existence and call arity/type checks
- [x] Mutability and shadowing checks
- [x] Loop legality checks (`break`/`continue` usage)
- [x] Return-path checks for typed functions (current language scope)
- [x] Assignment target legality (`identifier` or `.*`)
- [x] Pointer mutability write checks (`*i32` vs `*mut i32`)
- [x] Unwrap operator validation (`.?` and `.!` type expectations)
- [ ] Complete advanced type system semantics beyond current baseline
  - [ ] Full optional/error type propagation model
  - [ ] Full pointer element-type tracking (not just mutability category)

### 4) IR + Lowering
- [x] Stack IR core instruction set
- [x] Control flow lowering (`if`, `for`, `match`, short-circuit ops)
- [x] Multi-function/module call lowering
- [x] String rodata lowering
- [x] Pointer IR ops
  - [x] `addr_of_local`
  - [x] `load_ptr`
  - [x] `store_ptr`
- [~] Optional/error unwrap lowering semantics
  - [x] Frontend semantic validation
  - [ ] Runtime behavior model in IR (non-pass-through)

### 5) Native Backend (Direct ASM)
- [x] x86_64 Linux executable generation
- [x] Object generation and linking flow
- [x] Cross-module symbol linking
- [x] ABI validation checks (arg count/type, symbol conflicts, missing symbols)
- [x] Stack-frame alignment baseline (16-byte granularity)
- [x] Callee-saved clobber safety baseline (`rbx` no-clobber path)
- [x] Pointer load/store codegen for local-address pointers
- [ ] Expand backend for richer memory model (heap/globals/compound pointers)

### 6) Incremental Build + Cache
- [x] Module-level fingerprint cache
- [x] Reverse dependency invalidation
- [x] Rename/delete/move invalidation tests
- [x] Fingerprint includes target/kind/strategy/toolchain version
- [ ] Optional: content-hash caching and shared cache store

### 7) CLI / Build UX
- [x] `check`, `build`, `run`, `clean`
- [x] Per-command help
- [x] `--work-dir`
- [x] `run -- <args...>` passthrough
- [x] JSON output (`check`, `build`, `clean`)
- [x] Exit code behavior documented
- [ ] Optional: JSON schema parity for `run` and richer machine-readable diagnostics

### 8) Testing
- [x] Parser/semantic/lowering/backend unit tests
- [x] CLI integration tests
- [x] Golden diagnostics snapshots
- [x] Nested-module end-to-end fixtures
- [ ] Add more conformance tests for advanced pointer/optional/error semantics once runtime model is finalized

### 9) Documentation
- [x] Spec baseline (`docs/spec-v1.md`)
- [x] CLI reference
- [x] Cache behavior doc
- [x] Modules guide
- [x] Platform policy + ABI doc
- [ ] Keep README TODO synced with implementation progress each milestone

### 10) Major Remaining Milestones (High Priority)
- [ ] Implement full optional/error runtime semantics (`.?`, `.!`) in IR + backend
- [ ] Implement richer pointer type/value model (element type-aware operations)
- [ ] Decide and implement memory/runtime model (heap allocation, ownership/lifetimes, or explicit manual model)
- [ ] Add optimizer passes (constant folding, dead code elimination, simple CFG cleanup)
- [ ] Add minimal standard library / built-ins for IO (hello-world printing path)

### 11) Future / Stretch Goals
- [ ] C interop and FFI surface hardening
- [ ] Additional target platforms
- [ ] Packaging/distribution story
- [ ] Language server / formatter / lint tooling

