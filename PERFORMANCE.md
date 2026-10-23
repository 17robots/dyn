# Performance qualification

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
