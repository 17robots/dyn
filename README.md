# The Dyn Language

## Quick Commands
- Build CLI: `zig build`
- Run full test suite: `zig test src/backend_driver.zig`
- Check a program: `zig build run -- check path/to/main.dyn`
- Build executable: `zig build run -- build path/to/main.dyn -o out/app`
- Run program: `zig build run -- run path/to/main.dyn`
- Run std hello example: `zig build run -- run example_std/main.dyn --std-dir std`
- Run std allocator example: `zig build run -- run example_std_alloc/main.dyn --std-dir std`
- Clean intermediates: `zig build run -- clean`

## Current Priorities (This Week)
- [~] Implement full optional/error runtime semantics for `.?` and `.!` in IR + backend (runtime checks now lowered/codegen'd; full propagation model still pending)
- [~] Implement richer pointer type/value model with element-type-aware operations (semantic checker now tracks pointer element types; runtime slot/global/heap-pointer plumbing is in place; full aggregate model still pending)
- [~] Define and implement memory/runtime model (globals + pointer-space runtime + `__dyn_os_*` backing allocator symbols implemented; heap policy and ownership/lifetime rules still pending)

## Known Bugs
- Pointer/unwrap runtime model remains partial: `.?` and `.!` now lower to runtime-checked IR/backend ops, but full optional/error propagation/value modeling is still pending.
- Semantic checker currently has a gap around some alias field-call forwarding forms (e.g. `Alias.func(arg)` wrappers), which blocks fully layered std wrappers and forces temporary intrinsic-backed std entrypoints.

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
  - [~] Full pointer element-type tracking (semantic layer now tracks element type; runtime/value layer still pending)
  - [ ] Fix alias field-call argument resolution in wrapper functions (`Alias.func(arg)` should resolve `arg` correctly)

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
  - [x] Runtime behavior model in IR (non-pass-through)

### 5) Native Backend (Direct ASM)
- [x] x86_64 Linux executable generation
- [x] Object generation and linking flow
- [x] Cross-module symbol linking
- [x] ABI validation checks (arg count/type, symbol conflicts, missing symbols)
- [x] Stack-frame alignment baseline (16-byte granularity)
- [x] Callee-saved clobber safety baseline (`rbx` no-clobber path)
- [x] Pointer load/store codegen for local-address pointers
- [~] Expand backend for richer memory model (globals + slot-offset pointer ops + `__dyn_os_*` + std allocator intrinsics implemented; typed heap/value model still pending)

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
- [x] `--std-dir` fallback for `use "std/..."`
- [x] `run -- <args...>` passthrough
- [x] JSON output (`check`, `build`, `run`, `clean`)
- [x] Exit code behavior documented
- [x] Optional: JSON schema parity for `run` and richer machine-readable diagnostics (`dyn-cli.v1` schema + per-command diagnostics arrays)

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
- [x] Keep README TODO synced with implementation progress each milestone

### 10) Major Remaining Milestones (High Priority)
- [ ] Implement full optional/error runtime semantics (`.?`, `.!`) in IR + backend
- [~] Implement richer pointer type/value model (semantic element-type awareness + runtime slot-offset/global/heap-pointer support done; full aggregate/typed heap model still pending)
- [~] Decide and implement memory/runtime model (current local/global model + `__dyn_os_*` backing allocator + std allocator intrinsic path implemented; ownership/lifetime policy still pending)
- [ ] Add optimizer passes (constant folding, dead code elimination, simple CFG cleanup)
- [~] Add minimal standard library / built-ins for IO (working `std/io.print(string)` + allocator intrinsic path; layered std wrappers and richer APIs still pending)

### 11) Detailed Next Steps (Handoff)
- [ ] **Fix wrapper call semantic gap first (unblocks std layering)**
  - Repro pattern to fix: wrapper funcs like `pub f := (x: i32) i32 => Alias.g(x)` currently mis-handle arg resolution in some modules.
  - Primary files: `src/semantic.zig`, `src/resolver.zig`.
  - Verify with focused fixture under `example_std_*` plus `zig test src/semantic.zig`.
- [ ] **Replace temporary intrinsic aliases with real std forwarding layers**
  - Current backend supports temporary intrinsic names: `mio_print`/`mprint_print`, `mpage_allocator_*`, and alias fallbacks (`mheap_*`, `mmem_*`, `mallocator_*`).
  - After semantic fix, change std modules to true forwarding chain:
    - `std/mem` -> `std/mem/allocator`
    - `std/mem/allocator` -> `std/heap/page_allocator`
    - `std/heap/page_allocator` -> runtime backing (`__dyn_os_*`) via stable language surface.
  - Then remove fallback intrinsic name aliases incrementally from `src/backend_native.zig`.
- [ ] **Stabilize allocator API surface (MVP)**
  - Keep phase-1 signatures as `i32` pointer-sized values for now (current language baseline), but document migration to pointer-typed APIs.
  - Ensure alloc/free/realloc semantics match docs in `docs/27_AllocatorABI.md` (null/zero-size/alignment behavior).
  - Add conformance tests for alloc/free/realloc success + failure + realloc copy behavior.
- [ ] **Flesh out std collections using allocator path**
  - First target: `std/collections/array_list` with `init/deinit/append` backed by allocator calls.
  - Gate on semantic wrapper fix so module layering stays clean.
  - Add end-to-end fixture showing append growth and final value checks.
- [ ] **Promote compiler-bundled std default path (Zig-style)**
  - Keep `--std-dir` override.
  - Add default std root derived from compiler install location in CLI (`src/main.zig`) and pass through existing `std_dir` plumbing.
  - Keep resolution precedence explicit and documented (project-local vs override vs bundled default).
- [ ] **Complete optional/error propagation model**
  - Keep current runtime unwrap checks.
  - Add IR/type-level optional/error propagation rules so unwrap is not the only modeled behavior.
  - Expand tests in `src/lower_ir.zig` and `src/backend_native.zig` for mixed call/control-flow propagation.
- [ ] **Suggested verification checklist for each milestone PR**
  - `zig test src/semantic.zig`
  - `zig test src/lower_ir.zig`
  - `zig test src/backend_native.zig`
  - `zig test src/backend_driver.zig`
  - `./zig-out/bin/dyn run example_std/main.dyn --std-dir std`
  - `./zig-out/bin/dyn run example_std_alloc/main.dyn --std-dir std`

### 12) Future / Stretch Goals
- [ ] C interop and FFI surface hardening
- [ ] Additional target platforms
- [ ] Packaging/distribution story
- [ ] Language server / formatter / lint tooling

