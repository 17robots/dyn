# Remaining compiler performance work — 2026-09-21

All five requested areas were investigated and changed: source preparation,
LSP interfaces, type/member lookup, build scheduling, and LLVM debug preparation.
No optimization level, language rule, diagnostic behavior, or SDK allocation
interface was changed.

## Measurements

Optimized C compiler, same host, three fresh uncached processes per workload,
median milliseconds. OS caches were not flushed. Raw samples, compiler hashes,
phase details, RSS and scheduler samples are in
[the measurement artifact](remaining-performance-2026-09-21.json).

| Workload | Before | After |
| --- | ---: | ---: |
| Unicode SDK check | 183.46 | 107.39 |
| Unicode SDK debug build, no link | 211.29 | 134.85 |
| Unicode SDK release build, no link | 246.66 | 174.39 |
| 2,048 types, check | 110.55 | 92.34 |
| 2,048 fields, 8,192 accesses, check | 68.51 | 44.88 |
| Same field workload, semantic phase only | 6.287 | 0.141 |
| 2,048 locals, debug build, no link | 74.52 | 25.31 |
| Same local workload, LLVM generation only | 47.994 | 3.515 |
| 1,000 functions, debug build, no link | 73.01 | 69.40 |
| Serialized editor diagnostics, 300-function dependency | 4.83 | 4.29 |
| Ten-edit bursts, same editor fixture | 4.85 | 4.35 |

Editor rows use twenty samples. Their gains are modest and sensitive to host
noise. Unicode check peak RSS fell from 94,660 to 65,036 KiB; release build peak
RSS fell from 131,384 to 109,404 KiB.

The isolated scheduler benchmark uses four synthetic jobs costing 40/1/40/1 ms.
Two workers took a median 80.35 ms with the former round-robin policy and 41.41 ms
with the shared work queue. One hundred empty single-worker plans took 7.24 ms
with fork-based dispatch and 0.12 ms with direct execution. These isolate
scheduler overhead and imbalance; actual project gains depend on module costs.

## Changes and evidence

1. **Source preparation.** A profiler identified millions of calls through the
   target scanner on the Unicode fixture. A substring rejection avoids scanning
   files without any possible directive; the existing scanner still handles
   comments and strings. Scope indexing stops at expressions, which cannot
   introduce bindings. Merging reuses the largest prepared input tree through
   prefix/suffix edits and incremental reparsing. Large constant tables retain
   subtrees instead of starting another complete parse. Input trees remain
   immutable. The parse timing now excludes incremental work performed during
   merging, so the near-zero standalone parse phase is not itself a speedup
   claim; compare total time.
2. **LSP interfaces.** Canonical payloads use a bounded cache keyed by exact
   rewritten source contents, ordered paths, and target. Project loading still
   reads disk and applies overlays before lookup. Cache failures fall back to
   normal generation. The live LSP regression asserts interface reuse, and disk
   tests cover same-size/preserved-mtime edits, deletion and recreation.
3. **Type/member lookup.** A shared append-only name index serves AST types and
   aliases plus semantic struct/enum/member lookup. Small collections remain
   linear. Module checks and first-declaration selection remain authoritative.
   Repeated member benchmarks confirmed a quadratic semantic cost; the new
   scaling gate fails on the old compiler and passes on the new one.
4. **Build workers.** One worker runs directly. Multiple workers claim the next
   module through a process-shared lock-free atomic cursor, with round-robin
   fallback when that atomic is not lock-free. Results and error selection stay
   in source order. Tests cover success, callback errors, child failure, and
   interrupted waits.
5. **LLVM preparation.** Debug local lookup previously scanned all IR statements
   per local, and source locations repeatedly counted original-source lines.
   Declaration and line indexes remove those repeated scans. Release builds
   skip debug-only local work. Unwind frames are created lazily in the entry
   block for protected calls and reused inside loops. Actual panic/defer cleanup
   order, double panic, debugger locations and bounded-stack loops pass.

LLVM's optimization pipeline and emission settings remain unchanged. Unicode
release optimization still costs about 38 ms and emission about 20 ms. The
1,000-function debug build improved only modestly; this work does not establish
that the remaining LLVM emission cost is avoidable.

## Validation

- Normal and ASan/UBSan frontend, allocation-failure, cache and codegen checks.
- Merged incremental/fresh trees compared node types, byte ranges and points;
  indexed/original location calculations compared across all bytes and EOF.
- Runtime indexed-type/alias/member/variant/module ownership tests, debug/release.
- 51 LSP contracts; 66 incremental/fresh editor comparisons; queued edits and
  partial-frame barriers; headless Neovim completion; 137 project/SDK LSP files.
- 110 SDK/project modules checked, zero failures.
- Compiler diagnostics/contracts; 192 typed metamorphic builds; incremental
  private/public/transitive/reflection cache tests; constant-array tests.
- Debugger multifile checks, panic/defer/double-panic and loop checks, normal and
  sanitized compiler; broader runtime/SDK audit contracts.
- Seed 29 differential fuzz: 136 versions across check/build and incremental/full
  editor analysis.
- Independent C translation-unit build; static analysis of all 26 units, no
  warnings.
- Existing allocation/RSS/editor scaling gate and wide-function gate pass.
  New repeated-member/debug-local gate fails on the saved baseline and passes
  after the fixes.

No additional native platform tests were performed. Measurements describe these
fixtures and this host, not a claim that all compiler performance work is done.
