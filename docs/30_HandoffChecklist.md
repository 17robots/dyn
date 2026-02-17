# Handoff Checklist

This checklist breaks the current roadmap into concrete implementation slices with clear done criteria.

## 1) Fix Wrapper Call Semantic Gap

- [ ] Reproduce and isolate failing wrapper pattern (`Alias.func(arg)` forwarding) in a focused fixture.
- [ ] Fix argument resolution/type-check path for alias field calls in wrapper functions.
- [ ] Ensure wrappers work in same-file and cross-module contexts.
- [ ] Add regression tests in semantic/resolver suites.

Done when:

- `pub f := (x: i32) i32 => Alias.g(x)` resolves and type-checks reliably.
- Existing semantic/resolver tests still pass.

Primary files:

- `src/semantic.zig`
- `src/resolver.zig`

## 2) Replace Temporary Intrinsic Aliases with Layered Std Calls

- [ ] Switch `std/io` to forwarding wrappers (no temporary fallback behavior required in user-facing std API).
- [ ] Switch allocator flow to full chain:
  - `std/mem` -> `std/mem/allocator`
  - `std/mem/allocator` -> `std/heap/page_allocator`
  - `std/heap/page_allocator` -> runtime backing path
- [ ] Remove intrinsic alias names incrementally from backend once wrappers are stable.

Done when:

- Std modules can forward through alias calls without semantic failures.
- Backend supports only intended stable std entrypoints.

Primary files:

- `std/io.dyn`
- `std/io/print.dyn`
- `std/mem.dyn`
- `std/mem/allocator.dyn`
- `std/heap/page_allocator.dyn`
- `src/backend_native.zig`

## 3) Stabilize Allocator Surface (MVP)

- [ ] Confirm behavior for size/alignment/null/OOM matches `docs/27_AllocatorABI.md`.
- [ ] Add explicit conformance tests for alloc/free/realloc success and edge cases.
- [ ] Document current pointer-size assumptions and migration plan to typed pointers.

Done when:

- Allocator behavior is deterministic across interpreter/direct-asm paths.
- Tests cover both nominal and failure/edge behavior.

Primary files:

- `src/backend_native.zig`
- `docs/27_AllocatorABI.md`

## 4) Implement First Real Collection (`ArrayList`)

- [ ] Add `init/deinit/append` behavior in `std/collections/array_list.dyn`.
- [ ] Route growth through std allocator APIs.
- [ ] Add fixture validating append/growth and value retrieval path.

Done when:

- End-to-end example allocates, grows, and frees list storage.

Primary files:

- `std/collections/array_list.dyn`
- `example_std_alloc/main.dyn` (or dedicated fixture)

## 5) Add Compiler-Bundled Std Default (Zig-Style)

- [ ] Keep `--std-dir` override behavior.
- [ ] Add default std root discovery from compiler install location.
- [ ] Thread default std path through existing pipeline options.
- [ ] Document final resolution precedence clearly.

Done when:

- `dyn run app/main.dyn` works with bundled std without requiring `--std-dir`.

Primary files:

- `src/main.zig`
- `src/pipeline.zig`
- `src/module_graph.zig`
- `docs/19_CLI.md`
- `docs/22_ModulesGuide.md`

## 6) Complete Optional/Error Propagation Model

- [ ] Extend beyond unwrap-only runtime checks to full propagation semantics.
- [ ] Define/implement IR-level representation for propagated optional/error values.
- [ ] Add lowering/backend tests for propagation through calls/branches/loops.

Done when:

- Optional/error values propagate consistently and are not modeled only by unwrap ops.

Primary files:

- `src/semantic.zig`
- `src/lower_ir.zig`
- `src/ir.zig`
- `src/backend_native.zig`

## Verification Commands (Per Milestone)

- `zig test src/semantic.zig`
- `zig test src/lower_ir.zig`
- `zig test src/backend_native.zig`
- `zig test src/backend_driver.zig`
- `./zig-out/bin/dyn run example_std/main.dyn --std-dir std`
- `./zig-out/bin/dyn run example_std_alloc/main.dyn --std-dir std`
