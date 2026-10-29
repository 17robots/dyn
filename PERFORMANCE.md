# Performance qualification

## Allocations, editor latency and debug builds — 2026-10-29

A DNA release build made 720,000 heap allocations; it now makes 212,000.
Name lookups during import rewriting and reference checks copy names into
inline buffers instead of the heap. SSA block, predecessor and call argument
lists come from a per-function arena released at once. Passes take one block
for all their scratch arrays. IR keeps every declaration and local name in
one pool. Rewrite replacement texts come from a per-file arena. Short AST
blocks collect statement ids on the stack.

Editor analysis in `dyn lsp`, measured as the time from a one-character edit
of DNA's main.dyn to its diagnostics, falls from a median of 192 ms to 53 ms:

- The syntax cache held 64 entries and 8 MiB, fewer than one project's
  sources, so least-recently-used eviction missed on every file of every
  edit. It now holds 4096 entries and 128 MiB.
- Rewritten imports patch their trees under a work budget too, charging about
  what parsing would cost.
- Line and column lookup counts newlines with `memchr`, and source maps and
  edit spans are binary searched.

Interleaved medians for DNA:

| | Before | After |
|---|---|---|
| Release build | 140.5 ms, 126 MiB | 112.4 ms, 129 MiB |
| Debug build | 118.5 ms, 105 MiB | 91.6 ms, 101 MiB |
| `dyn check` | 67.0 ms, 59 MiB | 50.1 ms, 66 MiB |
| Editor edit | 192 ms | 53 ms |

Objects stay byte-identical on 46 project and target builds. The debug
build's tree emitter, about 31 ms, remains serial.

## Parallel frontend — 2026-10-29

Function bodies lower to the AST on up to four worker threads. Each worker
lowers a run of bodies into private arrays; the runs merge in function order,
shifting their ids and interning new types in creation order, which assigns
exactly the serial ids. A run that reports a diagnostic sends the whole
program back to serial lowering, so messages keep their order. Structure
checks of declarations and bodies also run on workers, and each body is
walked once instead of twice.

Serial work also shrank: type predicates are inline, import rewriting
resolves each file's directory once instead of four times, and IR lowering
builds the source location index once and resolves each SDK path once. The
backend's default worker cap rises from four to six; its smaller window keeps
the memory cost to about 4 MiB.

DNA, interleaved medians: 140 → 117 ms wall, 334 → 345 ms CPU,
127 → 132 MiB peak RSS. Stages: import loading 27 → 20.5 ms, AST lowering
23 → 14.5 ms, type checking 17.4 → 14.7 ms, IR lowering 10.8 → 8.7 ms.
Objects stay byte-identical on 46 project and target builds.

Runs merge in order as soon as each finishes, so only runs still in flight
exist beside the program; a run that reports a diagnostic truncates the
program back to its earlier counts before the serial retry. Worker heap
arenas would otherwise hold the merged runs' memory for the rest of the
build, so glibc builds return it with `malloc_trim` after the merge.

Import loading falls from 20.5 to about 17 ms. Imported directories load
from a work queue as soon as an import names them, instead of level by level
with a barrier after each level. Sources copied out of the prefetched
directories keep their snapshot's facts instead of walking every node again.

`dyn check` on DNA falls from 66 to 50 ms; its peak RSS, set during AST
lowering, rises from 60 to 64 MiB. Linking DNA takes 2.4–5 ms of a full
release build, so the linker is not a bottleneck.
A parallel inliner was measured and dropped: rebuilding bodies is memory
copying, and the merge copied it again for no gain and 10 MiB more peak RSS.
Type checking stays serial because instantiating generics creates functions
whose ids later checks depend on.

## Compiler throughput and memory — 2026-10-29

The native backend now prepares functions on up to four worker threads, at
most 16 functions per worker ahead of in-order emission on the calling thread.
`DYN_BACKEND_JOBS` overrides the worker count. String literals prepared on
workers are interned in encounter order at emission, so objects stay
byte-identical to serial builds.

Algorithmic changes cut single-threaded work as well:

- The range prover indexes branch facts by value and tests dominance in O(1)
  with dominator-tree DFS intervals; CSE uses the same test.
- Liveness groups cross-block uses by value, so no block is walked twice for
  one value.
- Optimization rounds stop after five passes in a row change nothing, and
  operand resolution runs only after a pass that changed something.
- Range queries are memoized within each prove pass.
- Load forwarding skips its second region classification when nothing was
  forwarded, and forwards runs of disjoint same-base stores across
  straight-line blocks.
- Import rewriting patches the parsed tree instead of reparsing each file:
  renames shift offsets and `alias.member` collapses into one name. Edits of
  any other shape still reparse.
- The inliner appends to the expression and statement arrays in place instead
  of copying them first.
- The parser handles literal tokens before testing keyword spellings, which
  halves the load time of generated data tables.
- Struct layout is memoized per object.

Byte fills of global byte arrays now apply at O2 as well as O3 (x86 only).
They are the only intended code change; all other changes keep objects
byte-identical on 46 project and target builds.

Interleaved medians, x86_64 Linux, release object builds without caches,
measured with `tools/bench/compile.py`:

| Project | Before | After | CPU before / after | Peak RSS before / after |
|---|---|---|---|---|
| DNA (62k lines) | 461 ms | 141 ms | 550 / 339 ms | 154 / 127 MiB |
| http-server | 25.3 ms | 13.6 ms | | 36 / 42 MiB |
| std fixture | 27.4 ms | 16.7 ms | | 26 / 34 MiB |

DNA single-threaded (`DYN_BACKEND_JOBS=1`) falls from 348 to about 230 ms.
Sieve runtime falls from about 1.23x to 1.17x of `cc -O2`. Small projects use
a few MiB more peak RSS because the worker threads and their stacks dominate.

The remaining serial cost is the frontend: AST lowering, type checking and IR
lowering take about 55 ms of DNA's build before the backend can start.

## Real-application follow-up — 2026-10-20

The real-project matrix covers a 10.8 MB JSON validation input, a PTY-driven
Field Notes session, DNA's existing document-buffer workload, and its complete
headless search/open/edit/undo workflow. JSON and Field Notes require isolated
API-adapted copies because the checked-in examples use retired memory APIs.
DNA sources and its buffer workload remain unchanged. Both compilers use the
same staged sources, input bytes, SDK and native libraries.

Five paired cold-build samples measure JSON at 160,384 / 42,688 bytes and about
30.7 / 10.8 ms before/after all changes. Field Notes measures 81,112 / 35,664
bytes and about 9.7 / 7.6 ms. DNA's buffer remains 149,384 bytes; the editor falls
only from 1,564,040 to 1,559,944 bytes, with build time roughly unchanged near
0.31 s. External inputs conservatively preserve public roots, limiting pruning
benefits in these two applications.

Runtime profiling finds PCRE2 as the editor's largest sampled leaf. Its replay
also contains scheduled waits, so its approximately 43 s wall duration is not
an interactive-latency measure. The 30-run GDB/MI JSON profile records string
scanning in 99 of 131 PC samples. These are directional samples, not hardware
cycle counts. Disassembly exposes repeated loads of unchanged cursor fields.

A new SSA pass reuses identical typed loads only within one basic block.
Memory writes, calls and copies invalidate reuse; no pointer non-aliasing or
cross-block assumptions are added. Fifteen shuffled runtime samples recover
the intermediate compiler's JSON regression: about 14.9 / 12.8 ms immediately
before/after load reuse. The original compiler also measures about 12.9 ms,
so the cumulative result retains smaller code while restoring original speed.
The standalone cursor and DNA buffer benchmarks show little runtime change.
This is not a general runtime speedup claim.

Separate native-launcher measurements avoid Python's inherited RSS floor.
JSON remains about 10.3 MiB peak RSS; Field Notes about 0.5 MiB; the buffer
workload varies around 4–5 MiB. No meaningful allocation reduction is shown.
The editor's final integration run records 50.6 MiB peak RSS; its single final
sample does not establish a memory improvement over the earlier paired runs.

The complete compiler suite and the focused load-reuse gate pass. The new
code-generation assertion fails on the preceding compiler, which emits two
reads of the same pointer instead of one. Tests preserve aliasing stores,
partial writes, calls, overlap copies, zeroing, branches and loop-carried writes.
The rebuilt editor passes its workflow probe and matches full-reference Unicode,
tab and zoom rendering pixel-for-pixel. Raw data and scripts are retained under
`build/real-app-performance/`; the cursor benchmark lives in
`tests/performance/cursor`, and the gate is `tests/native-load-reuse.py`.

## Independent backend update — 2026-10-20

Native release executables now compute function reachability before scalar
optimization and inlining. Unused public bodies are skipped when the compiler
has the complete executable and no external link inputs. Explicit object or
assembly output, libraries, debug output, and Wasm retain their public-root
policies. Global initialization, callback addresses, and cleanup remain live.
Object cache keys distinguish builds with external public roots, so adding an
external object cannot restore an executable object with required symbols pruned.

O3 uses cached expression-aware callee costs and a program expansion budget.
ELF x86-64 code sections now declare the 16-byte alignment required by SSA loop
padding. Detailed timings separate reachability, scalar optimization, inlining,
SSA construction/optimization, register allocation, machine emission, and object
serialization. Backend totals aggregate per-function work and sit inside the
overall native emission time; they are not additional command wall time.

Seven shuffled samples after warm-up on this Linux x86-64 host measured the
standard-library fixture as follows. Portable O2 executable size falls from
143,592 to 36,928 bytes; cold build median falls from 29.30 to 10.04 ms. O3 size
falls from 310,560 to 37,240 bytes; build median falls from 112.91 to 10.56 ms.
The five smaller kernels produce O2 files about 32% smaller, with build times
about 9–17% lower. Compiler caches are disabled; OS caches remain warm.

Runtime is workload-dependent: O2 Fibonacci is about 2.6% slower, O3 matrix
about 8.1% faster, and O2 sieve about 4.8% faster. Other changes are small.
Every output/checksum matches. These samples establish size/build improvements,
not a universal runtime improvement. The comparison uses a preserved pre-change
compiler binary, not a fresh rebuild of old sources.

The complete standalone regression suite passes after the final alignment fix.
New tests check seven-target executable pruning, retained exports and external
callbacks, initializer/defer effects, cache reuse, ELF code alignment, and bounded
inlining. The growth regression fails with the old compiler: its O3 object grows
from 3,832 to 18,240 bytes. The new compiler passes the growth limit.

Raw commands, samples, compiler/artifact hashes, and logs are retained locally
under `build/performance-implementation/`. Final paired samples after the cache fix are in
`final-measurements/results.json`; `compare-aligned.py` reproduces them when the
preserved baseline is available. These are local artifacts, not shipped SDK data.

## Historical LLVM measurements

The remainder predates the independent backend and must not be used as its
current baseline.

Local measurements from 2026-10-04, AMD Ryzen 9 9950X, Linux, LLVM/LLD 23.
The new compiler controls also passed executable regression tests with LLVM/LLD
19, the packaged release toolchain. Times are workload-specific, not promises.

## Compiler findings and decisions

- The earlier DNA hot-helper extraction regressed its synthetic runtime workload
  by about 9% on preview 14 / LLVM 19. Disassembly shows out-of-line helpers in
  the split binary while the same-module binary inlines them. On LLVM 23, remarks
  report `add_text` cost 265 versus O2 threshold 225 and O3 threshold 250;
  `fuzzy_score` remains out of line. Do not force global inlining thresholds or
  promote that extraction. Keep hot helper/caller groups together.
- A fresh LLVM 23 control comparison (five alternating runs) measured 1.001s
  same-module O2, 1.024s split O2, 1.027s split O3, and 0.864s split/native CPU.
  These are not directly comparable to the earlier LLVM 19 timings. Native CPU
  tuning helps that workload but barely changes the std workload below.
- Release builds with debug info explicitly attached `noinline` to every Dyn
  function. This restriction is removed; optimized debug builds can now inline.
- Sample-PGO tests prove LLVM applies body samples and changes hot-call inlining
  decisions. Test profiles are synthetic: no trained DNA PGO speedup is claimed.
  Collection/conversion remains the external profiler's job.
- The existing backend already lowers large value copies through bounded memory
  operations, applies target ABI `sret`/`byval` alignment, and tracks guard facts
  with invalidation across calls/mutations. The regression suite covers these
  seams. No blanket `noalias`, unchecked accesses or lifetime assumptions were
  added: `const` pointers can alias, and incorrect promises would miscompile code.
- No new language syntax or runtime dependency is needed for these improvements.
  Portable O2 stays the default; CPU specialization and O3 remain explicit.

## Standard-library proof

`tests/performance-contracts.py` compares prepared KMP and normal forward/reverse
search against Python byte-search oracles, including empty/binary data and
repeated prefixes. It also checks map reservation/rehashing/deletion/clear,
allocation failure, builder overlap and interleaved allocations, and buffered
write ordering, short writes, partial/sticky errors and every small chunk boundary.

A repeated-prefix search case (32 KiB text, 128-byte needle, 200 searches, five
alternating samples) measured 153.85ms before the tail filter, 3.34ms after, and
15.99ms with prepared KMP. This intentionally pathological case is not an editor
speedup claim. The tail filter remains potentially quadratic; prepared KMP gives
linear search with caller-owned prefix storage for repeated/adversarial searches.

Appending 1,000 single bytes to an initially empty arena-backed builder now uses
1,024 backing bytes instead of retaining successive 64/128/256/512/1024-byte
buffers (1,984 bytes). Interleaved allocations still require copying. Map
reservation avoids intermediate tables; removal/clear still retain key storage.
These contracts are explicit so applications can choose arena lifetimes correctly.

## Repeatable matrix

Run `python3 tools/performance-suite.py --samples 7` to retain JSON samples,
compiler/source hashes, output checksums, executable sizes and child resource use.
The fixture exercises byte search, comparison/copy, UTF-8 decoding, container
operations and builder growth, reporting arena usage/peak/failures. These are
combined workload timings, not independent per-operation throughput figures.

Five-sample local medians, seconds:

| Policy | Cold build | Unchanged | Novel code edit | Runtime |
|---|---:|---:|---:|---:|
| Portable O2 + ThinLTO | 0.189 | 0.040 | 0.100 | 0.173 |
| Native CPU + ThinLTO | 0.206 | 0.039 | 0.102 | 0.172 |
| O3 + ThinLTO | 0.199 | 0.040 | 0.099 | 0.165 |
| O2 without LTO | 0.206 | 0.040 | 0.077 | 0.159 |

All runtime checksums and arena counters match: checksum 322372743, used/peak
12,288 bytes, zero allocation failures. This workload does not justify changing
defaults. Cold means empty Dyn caches, not flushed OS page caches. Reported peak
RSS is an OS per-child maximum, not aggregate concurrent process-tree memory.

## DNA boundary experiment

Move language-server catalog/PATH discovery into `src/servers`, preserving the
existing application entry points and keeping private PATH helpers in that
module. Hot text helpers remain beside their callers. Three novel catalog edits:

| Mode | Before edit median | Extracted edit median |
|---|---:|---:|
| O2 + ThinLTO | 6.362s | 0.569s |
| O2 without LTO | 4.887s | 0.545s |

Single cold samples remain approximately unchanged: 6.508/6.563s with ThinLTO,
4.978/4.944s without. This improves incremental work, not cold compilation.
Catalog/PATH output matches before/after in debug and both release modes.
A five-million-lookup microbenchmark measured 0.163s before and 0.170s after
(five alternating samples, identical checksum). This is a small lookup slowdown,
not zero-cost abstraction; the boundary is retained because catalog discovery
is low-frequency and its edited-build improvement is substantial.
DNA's nine module test suites pass in debug/release; its release UI workflow
smoke test passes with SDL's dummy driver. This is functional proof, not an
interactive responsiveness benchmark.

The DNA change is separate from this compiler repository and sits atop the
user's existing work; unrelated concurrent terminal/scheduler edits were retained.
The old hot-helper extraction remains rejected. More cold-build improvement
requires further compiler/backend profiling, not indiscriminate module splitting.

## Validation

- Full standalone compiler suite, including ABI, unwind, alias-sensitive guards,
  aggregate copying, parser, network, LSP, cache and allocation-failure tests.
- Final focused optimization/cache/std contracts on LLVM 23; optimization and
  sample-profile execution also qualified with LLVM/LLD 19.
- Native host suite; native Windows/macOS validation remains with their CI jobs,
  which now include the new performance contract tests.

Local raw evidence is under `build/performance-work/` (ignored), including
`matrix-final-codegen/`, `search-proof/`, `dna/`, optimization remarks and test logs.
The checked-in fixtures and runners reproduce the compiler/std experiments.
