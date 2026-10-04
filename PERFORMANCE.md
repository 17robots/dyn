# Performance qualification

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
