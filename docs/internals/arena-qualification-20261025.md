# Pointer-arena qualification (2026-10-25)

The pointer/chained-arena migration has **225/225 registered gates accounted for
as passing**, including artifact construction and all 21 C artifact executions.
No prerequisite SKIP was reported by these gates on this machine. This is an
ordered registered run plus final focused reruns, not one unchanged-source run.
The native-error gate was registered and run after the ordered run completed.

The debug and release compilers were rebuilt with the strict project build.
Existing Python, Unicorn, QEMU/Podman, Node and Wine installations were reused;
no dependencies were installed. Run `python3 tests/run.py` with the matching
compiler/SDK and available target runners to reproduce the registered gates.

## Behavior and regression coverage

Constructors return `*mem.Arena`; headers live in backing storage. Owned arenas
chain blocks, while borrowed buffer arenas remain fixed. Explicit
`arena_create(0)` selects the target default. Backing limits include headers,
usage/peak counters exclude them, and marks are virtual positions. Rewind/reset
release later blocks; owned release invalidates its handle. Pointer aliases do
not create additional owners, and the language does not prohibit explicit
header copies. See the [migration guide](../migrations/arena-handles-20261025.md)
and [memory guide](../guide/memory.md).

Focused tests cover exact backing limits, arbitrary buffer alignment, allocation
failure state, zeroing, overlapping inputs, payload canaries, stable independent
allocations, scratch conflicts, moved list views, and normal/error ownership.
Actual Wine runs exercise Windows reservation/commit ordering and chained
rewind/reuse. Host-substituted Darwin tests exercise CString lifetime and watcher
close idempotence; these are not native Darwin execution.

Small-block producer tests deliberately start after prior growth. They cover
builder relocation, contiguous file/FIFO output, compact JSON tape relocation,
HTTP interim/final response storage, live Unicode compaction before rewind,
DNS, codecs, AEAD, and process capture. JSON tests also execute on all four
RV32/Thumb hard/soft configurations. Native-error substitutes retain nonzero and
zero diagnostics across host default/forced-tree modes and soft RV32/Thumb executions.

Retained pre-fix controls reproduce Windows header-write faults, incorrect peak
accounting, builder range corruption, JSON growth/trim/overlap failures, HTTP
response lifetime failure, and Unicode use-after-rewind. Exhaustion tests require
the allocation-exhaustion diagnostic rather than accepting a constructor-header
panic. Fixed C ABI adapters retain exact caller scratch capacities and
recoverable validation failures through `c.string_into`.

Final focused reruns cover the small native-growth-result change, including
Wine, core chain contracts, producer chains, JSON cross-target execution,
builders, files and Unicode. The HTTP relocation change was exercised by its
extended gate within the ordered run. An AEAD comment and test registration also
changed after the initial source snapshot. The local ledger records these
source deltas rather than claiming a frozen-source qualification.

## Additional workspace checks

All **46 external project modules** pass target-appropriate checks using the new
compiler and source SDK. Selected debug/release executions cover the memory
examples, Field Notes, HTTP/WebSocket loopback, recursive search, detached-terminal
startup, offline/dummy audio and ENet loopback. Browser canvas/video modules and
the WASI example also execute under Node. These external workspace files are
outside the standalone compiler repository and are not part of its PR.

Ten optional native vendor workflows pass debug/release, with independent C
oracles. A raw resize branch passes using a temporary syntax-adapted SDK overlay;
this is not qualification of the complete 23-provider raw suite. Legacy external
workspace tests outside the registered standalone runner are not universally
qualified by these results.

## Limits and evidence

- OS reservation errors retain their native code. Header-commit failure still
  exposes synthetic `-12`; ordinary page-commit failures panic. Exact Win32
  commitment diagnostics are not provided by the current boolean commit helper.
- Native Darwin and complete native Windows wrapper execution, physical boards,
  and universal allocation-failure coverage remain unestablished.
- This is correctness/compatibility qualification, not a fresh performance
  comparison. Chained observation and growth costs are documented in
  [costs](../guide/costs.md).
- The separate, already-dirty tree-sitter workspace received the safe comma-free
  case-arm update and passes 20 corpus cases plus generator checks. Its grammar
  remains permissive about statement line layout; the compiler enforces the new
  rule. The unsafe scanner prototype was discarded. The case-arm followup is isolated above the existing grammar
  PR, so its earlier cast/function-type work is preserved.
- This development SDK has not been published as an official preview.

Local commands, logs, pre-fix controls and fixtures are retained under
`build/arena-followup/`. The main records are `final-suite.log`,
`native-errors-final.log`, `qualification.json`, and
`qualified-source-hashes.json`. Additional focused logs and source snapshots
identify their individual controls. These local build artifacts are not shipped
in the source repository.
