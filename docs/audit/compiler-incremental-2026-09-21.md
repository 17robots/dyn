# Compiler build, dependencies and editor performance — 2026-09-21

Implemented the six follow-up improvements after the frontend performance pass.

## Implementation

1. `make release` produces `build/dyn-release` with `-O2`, independently of
   generated-program optimization. `make` retains the debug compiler, and
   `make install` installs the optimized compiler. No LTO or architecture-specific
   host flags are required.
2. Module rewrite edits and source spans grow geometrically. Duplicate edits are
   sorted and checked for agreement; overlapping/conflicting edits fail rather
   than choosing a replacement arbitrarily. Source-span lookup uses binary search
   and copying advances through spans instead of rescanning the whole map.
3. Resolved import edges produce transitive dependency sets. Module object keys
   hash syntax-delimited declaration surfaces of those dependencies, not textual
   occurrences of `pub ` throughout the project. Private types/constants remain
   dependencies because public declarations can expose them. Private function
   implementations are excluded. Public changes preserve unrelated objects.
   Interface composition uses the same dependency sets to omit unrelated modules.
4. Diagnostic publication retains checked per-module AST snapshots. It composes
   each module's implementation with dependency interfaces after loading fresh
   disk bytes and applying overlays. Cache hits require exact text and source maps.
   Unused-binding checks borrow that same analysis. Full-project analysis remains
   the fallback for errors/unsupported interfaces and the source for cross-module
   navigation, references and rename.
5. A bounded input framer supports nonblocking lookahead. Consecutive received
   edits are applied in order and analyzed together. Requests, other notifications,
   malformed envelopes and partial frames end a batch. Nothing waits for an
   incomplete next frame before publishing the completed edit. No background
   analysis threads or asynchronous cancellation are introduced.
6. `make perf-compiler` and `benchmarks/compiler-scaling.py` measure import counts,
   wide structs, qualified references, individual edits and ten-edit bursts.
   Reports contain raw wall-time samples, peak RSS, allocation calls/requested
   bytes, and median/p95/maximum editor latency. A baseline comparison fails on
   regressions beyond the documented noise allowances.

Reflection is deliberately conservative: enabling/disabling reflection changes
the object key, and reflection builds include all project implementation content.
Types introduced while lowering bodies must not preserve stale reflected metadata.
Removing reflection may reuse a matching older non-reflection artifact.

The module analysis cache retains at most 64 snapshots and 16 MiB of source/map
text, plus AST/tree/metadata overhead. Optional cache allocation failures preserve
caller ownership. Retained snapshots survive eviction and cache destruction.

## Validation

- Normal, optimized and ASan/UBSan incremental builds: unchanged/private/public
  edits, transitive public constants, unrelated object reuse, reflection mode
  changes and runtime exit values in debug/release output modes.
- 51 LSP contracts, incremental/fresh comparisons, same-size/preserved-mtime disk
  edits without watcher notifications, and module semantic cache hit/miss checks.
- Queued edits, UTF-16 text, partial framing, request barriers and malformed
  envelopes. The malformed-envelope regression was observed failing before its
  batching fix; reflection invalidation likewise has a reproducing regression.
- Cache allocation-failure and retained-snapshot eviction tests; frontend state,
  source loading and codegen failure checks under sanitizers.
- Compiler contracts/diagnostics, 192 metamorphic builds, dense/sparse/imported
  constant-array codegen, Unicode conformance, SDK library fixtures, project
  examples, and a relocated optimized SDK installation.
- Separate translation-unit build and static analysis of all 26 compiler files.

No additional native platform tests were run. Project validation retained the
environment's SDL GPU availability skip. SDK arena APIs are unchanged.

## Measured results

Milliseconds; baseline is the previous default compiler, final is `dyn-release`.

| Workload | Before | After |
| --- | ---: | ---: |
| 13-module cold build (one sample) | 97.81 | 58.28 |
| Unchanged build | 12.20 | 11.69 |
| Private-body edit | 20.25 | 21.11 |
| Public-interface edit | 77.03 | 20.32 |
| LSP individual edit | 7.92 | 4.11 |
| LSP ten-edit burst | 78.84 | 4.15 |
| Unicode SDK check | 198.33 | 186.17 |
| Unicode SDK release | 264.29 | 253.90 |

Private-body and unchanged builds show no reliable additional speedup in this
run; their existing reuse remains intact. Public-interface edits reuse 11 of 13
module objects instead of rebuilding all 13. Repeated scaling runs passed the
regression thresholds, including allocation counts, RSS and editor p95.

## Measurement scope and remaining limits

Raw results are retained in
[compiler-incremental-2026-09-21.json](compiler-incremental-2026-09-21.json).
Compiler phase runs use three samples; incremental runs use seven, except for a
single cold sample; editor runs use twenty individual edits and twenty bursts.
Compare small differences cautiously. Results combine algorithm changes and an
optimized host compiler; default-build measurements are retained separately.

The scaling suite exposed poor time scaling for a single function containing
thousands of qualified references. This pass removes edit-list/span-map overhead;
it does not eliminate all syntax traversal and name-resolution costs. Allocation
counts grow much more slowly than wall time in that workload. The benchmark now
makes this limitation visible and detects further regressions.

That specific hotspot was subsequently fixed in the
[large-function performance pass](large-function-performance-2026-09-21.md),
which adds indexed binding lookup and a focused scaling gate.

Real edits within a module still reanalyze that module. Error recovery may reanalyze
the whole project. Edits arriving during synchronous analysis are processed when
that analysis finishes; batching only removes obsolete work already queued.
Allocation instrumentation excludes allocations internal to shared LLVM,
Tree-sitter and libc libraries; process RSS includes them.
