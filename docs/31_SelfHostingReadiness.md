# Self-Hosting Readiness Plan

This plan lists the minimum capability slices needed to make writing the Dyn compiler in Dyn realistic.

## M1 - Usable Dynamic Sequence Primitive

- Stabilize `std/collections.ArrayList` as the first practical growable container.
- Keep explicit allocator flow (`mem -> allocator -> page_allocator -> runtime`).
- Provide basic storage path helpers for compiler workloads:
  - `init`
  - `deinit`
  - `grow`
  - `append`/`append_at`
  - `get`

Done when:

- End-to-end tests show append and retrieval path works through runtime-backed storage helpers.

## M2 - Core Compiler Collections

- Add map/set-like structures required by frontends (symbol table, interner table, visited set).
- Provide stable APIs for insert/get/contains/remove/iterate.

Done when:

- A small symbol-table fixture is implemented purely in Dyn.

## M3 - Text + Buffer Toolkit

- Add string/byte buffer builders and small formatting helpers.
- Add interned string utilities needed by lexer/parser/diagnostics.

Done when:

- A lexer-like fixture can tokenize source into dynamic buffers without host-language helpers.

## M4 - Error/Optional Propagation Completion

- Finish propagation model across semantic/lowering/runtime paths.
- Keep unwrap checks, but support full propagation semantics as first-class behavior.

Done when:

- Frontend-style functions can propagate errors without hand-rolled sentinel plumbing.

## M5 - File + Path + Process Std Surface

- Add practical std wrappers for file read/write, directory scans, and path utilities.
- Add process/env helpers sufficient for compiler driver tasks.

Done when:

- Dyn-based compiler driver fixture can discover files and load source text.

## M6 - Bootstrapping Loop

- Build a small Dyn implementation of one frontend phase (for example symbol collection) and run it via Dyn.
- Expand phase by phase until parser+resolver+semantic core is feasible in Dyn.

Done when:

- A non-trivial compiler subsystem is authored and executed end-to-end in Dyn.
