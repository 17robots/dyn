# Qualification record (2026-10-24)

The registered standalone compiler suite passes **183/183 gates**, including
artifact construction and all 21 artifact executions. This is combined evidence
from original and resumed runs, not one uninterrupted final-state run. No gate
reported a prerequisite SKIP. The final rerun from std lint onward passes all
140 remaining gates in runner order with the original timeouts.

The existing Python 3.11.15 / Unicorn 2.1.4 environment and QEMU wrappers were
reused. No dependencies were installed. Debug and release compiler binaries were
rebuilt before qualification. The runner is `tests/run.py`; it registers the new
IR, std contract, numerical, ABI, instruction-audit and failure regressions.

## Corrected qualification failures

1. A capture regression forged a slice descriptor at an unaligned arena offset.
   Python executable path length exposed the fixture error. The fixture now
   computes `#alignof([]const u8)` before constructing the descriptor.
2. New HTTP trailer-control cases used JSON escapes that Dyn does not accept.
   Fixture generation now emits Dyn byte escapes, including NUL and DEL.

Both failures were reproduced and fixed before the successful resumed gates.
Later review findings for WebSocket buffering, HTTP trailer validation,
clock-error propagation, stream diagnostics and template exhaustion have
retained regressions and fresh independent reviews.

## Final-state checks

The final 140-gate run changed no `src`, `std`, `runtime`, `vendor` or `tools`
content. Two test files changed while it ran: the optional vendor deadline
fixture was migrated, and clock-consumer tests gained an extra zero-code replay
assertion. The current clock-consumer test was rerun in the same Python 3.11
qualification environment. Function-type loading and WebSocket buffering tests
were also rerun there. Optional vendor provider execution is not claimed for the
updated deadline fixture; its Python syntax check passes.

Focused suites additionally cover real Linux clock EPERM through seccomp,
zero-code provider and stream failures, no additional reads after terminal
errors, output overlap and rollback, authenticated plaintext wiping, and child
reaping after capture failure or arena panic. Watcher platform substitutes are
explicitly distinguished from real Windows/macOS execution.

The self-hosted parser matches the C parser on 246 source files and 607 generated
inputs. Structural IR determinism and target-gated native math lowering pass
focused host, emulator and Wasm checks. Numerical sampling does not establish a
global accuracy bound.

## Evidence and remaining limits

Local machine-readable results, per-gate logs, source hashes and combined gate
ordering are retained under `build/std-closure-qualification/`, including
`combined-summary.json` and `combined-summary.txt`. Original/resumed console
logs are `build/std-closure-suite*.log`.

The development SDK is packaged, relocated and smoke-tested locally by
`tools/package-sdk.py`; its manifest and checksum are in `build/dist/`. It is not
an official published preview. Physical NUCLEO execution, complete native-host
qualification for every changed platform wrapper, and two real preview releases
without a breaking change remain unestablished. The historical focused
copy-reallocation fault-injection gap remains recorded separately; these passes
do not claim that omitted test.
