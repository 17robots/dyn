# Compiler and std readiness review (2026-10-24)

This review closes the implementation work identified by the embedded follow-up,
portable-math pass and the rule-by-rule std audits. It does not declare a published
compatibility freeze or start the self-hosted compiler.

## Implemented and reviewed

- Embedded RV32/Thumb hard- and soft-float paths, ABI handling, DWARF, stack
  guards and the supported SSA lowering have durable emulator regressions.
- Portable scalar and geometry math has independent numerical checks. Trusted
  calls use native instructions where target and CPU capabilities permit them;
  portable implementations remain available elsewhere.
- `--emit-ir` provides the versioned structural snapshot needed by the stage-3
  bootstrap oracle, before optimization or code generation.
- The std closure pass fixes the concrete arena-output, portable-diagnostic,
  sticky-error, zero-state and parser-stub violations found by the audits.
  Fixed-size primitives, raw OS/C bindings and documented streaming buffers
  retain their narrow exceptions. The lint gate checks syntax heuristics and
  is not the evidence for semantic compliance.

Independent reviews found and resolved additional overlap, diagnostic-offset,
WebSocket buffering, HTTP trailer-validation and clock-error propagation bugs.
Clock failures now remain structured through dependent network waits, profiling,
benchmarks and finite process capture. Regression fixtures include native error
zero and injected failures rather than relying on nonzero codes as failure flags.

## Qualification result

The registered suite passes 183/183 gates across combined runs; the final
140-gate rerun has no failures or reported prerequisite skips. A relocated
local development SDK passes package validation. See the
[qualification record](qualification-20261024.md) for corrected fixture failures,
source-state accounting and supplemental checks.

## Qualification limits

Linux x86-64 is the primary runtime host. ARM/RISC-V emulators, Wasm execution,
independent ABI oracles, soft-image instruction audits, Windows/macOS cross-links
and platform-call substitutes cover documented portions of other targets. These
are not universal native-platform qualification. Actual Windows/macOS execution
of every changed edge wrapper and an actual NUCLEO board run are not established.
Floating-point sampling is not a global transcendental accuracy guarantee.

The self-hosted parser currently matches the C parser on 246 source files and
607 generated inputs. The self-hosted compiler still needs to reproduce the
semantic, structural-IR and executable oracles described in the bootstrap plan.
The historical focused copy-reallocation fault-injection gap remains documented
in the embedded follow-up; unrelated passing suites do not establish that test.

## Next milestone

Record an explicit compatibility freeze, publish a preview, and pass a second
real preview without another breaking language or std change. No local archive
or development commit substitutes for those two releases. Then begin stage 0 in
[the self-host bootstrap plan](selfhost-bootstrap.md). Physical-board validation
remains a separate hardware milestone.

Breaking signatures and ownership rules are listed in the
[std migration notes](../migrations/std-contracts-20261024.md).
