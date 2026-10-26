# Dyn runtime performance: 2026-10-24

**Full C parity is not achieved.** Large search beats the selected C port; source search is close; JSONL remains substantially slower. This is a measured compiler/std improvement pass, not a language-wide ranking.

## Same-input paired comparison

Milliseconds, lower is better. Nine samples after two warmups, alternating/rotating process runs on CPU 2.

| Application | Before | Final Dyn | C | Speedup vs before | Dyn / C time |
|---|---:|---:|---:|---:|---:|
| JSONL reporter | 124.735 | 60.327 | 13.317 | 2.07× | 4.53× |
| 64.3-MB text search | 87.420 | 10.326 | 32.307 | 8.47× | 0.32× |
| 3.7-MB source search | 14.468 | 5.309 | 4.388 | 2.73× | 1.21× |

The operational all-application target of at most 1.2× C time remains unmet, chiefly because of JSONL. The source-search ratio is near that boundary and varies with startup/filesystem noise.

## Current application ports

These separately measured child-process times use the comparison harness and include startup/I/O; do not mix them with the host-wall paired table above. RSS is peak MiB.

| Port/library | JSONL ms | Search ms | JSONL RSS | Search RSS |
|---|---:|---:|---:|---:|
| Dyn std | 59.801 | 10.027 | 18.0 | 8.1 |
| GCC + yyjson | 12.317 | 31.984 | 15.4 | 2.4 |
| Clang + yyjson | 12.853 | 30.894 | 15.4 | 2.2 |
| Rust + serde_json | 42.260 | 44.901 | 15.1 | 2.2 |
| Go std | 182.423 | 12.953 | 49.0 | 13.9 |
| Node std | 70.364 | 69.096 | 98.7 | 69.1 |
| Python std | 235.949 | 78.236 | 47.4 | 18.8 |

C uses yyjson and ordinary byte-search library calls. Rust uses serde_json and standard slice windows for search. Go and Dyn use their byte-search primitives. Faster libraries or different application designs can change this ordering.

## HTTP

Five rounds, one server CPU and separate client CPUs, four clients, new connections, checked responses. Throughput includes client validation overhead. No C/Rust framework was selected.

| Std server | Requests/s | Single-client median ms | Four-client sample p95 ms | Peak RSS MiB |
|---|---:|---:|---:|---:|
| Dyn std | 9969 | 0.125 | 1.024 | 18.0 |
| Go std | 5352 | 0.217 | 1.065 | 17.0 |
| Node std | 7593 | 0.136 | 1.105 | 70.6 |
| Python std | 4663 | 0.224 | 1.277 | 20.9 |

## Original compute regressions

Same fixed source/checksums, generic code, nine paired samples. These are before/after regressions, not a fresh cross-language compute ranking.

| Kernel | Before ms | Final ms | Change |
|---|---:|---:|---:|
| fib | 23.660 | 23.707 | +0.20% |
| hash | 76.510 | 76.390 | -0.16% |
| matmul | 51.124 | 50.962 | -0.32% |
| points | 12.167 | 12.105 | -0.50% |
| sieve | 122.223 | 122.920 | +0.57% |
| json | 126.111 | 94.607 | -24.98% |

## Search stress cases

Opaque repeated calls, independent C checksum oracle, two warmups and nine paired samples. All seven final cases improve over the before compiler.

| Case | Before ms | Final ms |
|---|---:|---:|
| common-final-early-prefix-mismatch | 14.904 | 1.402 |
| long-prefix-late-mismatch | 22.343 | 13.688 |
| absent-final-byte | 8.215 | 2.091 |
| overlapping-matches | 16.224 | 9.405 |
| short-slices-repeated-find | 15.849 | 8.521 |
| absent-byte-long-slice | 7.859 | 1.736 |
| short-slices-repeated-byte | 20.861 | 13.391 |

## DNA

No DNA source edits. All 300 source hashes remain unchanged. Five qualified alternating pairs use each editor’s matching native library and runtime.

Median of per-run input means: **1.818 → 1.802 ms**. Median of per-run maxima: **2.305 → 2.477 ms**. Median RSS growth: **19560 → 19548 KiB**. Treat small changes as broadly stable, not proof of faster interaction or better tail latency. This measures input-update wall time under the workflow harness, not key-to-display latency.

One original pair was conservatively excluded after a 0.2-second corpus hash check overlapped harness execution; an extra pair replaced it. Both raw runs are retained. The checked-in workflow JSON identifies the qualified samples.

DNA release is 16,368 bytes smaller than the immutable before snapshot; its native library is 4,096 bytes smaller. Runtime objects are unchanged.

## Qualification and implementation

Final compiler SHA-256: `6e31b45bc6081dcec705fff28da87d1bc5fb9f6228183a9dade2ae4ffdd362cf`. Debug/release/all artifact builds pass. The final registered compiler suite passes **203/203 gates, zero skips**, in one uninterrupted final-state run with identical before/after source hashes. DNA passes **9/9 gates, zero skips**, including core modules, host/filesystem, native/platform ABI, optional old/new cast oracle, and editor smoke.

## Retained changes

- Inline eligible calls underneath bounded cast/conversion chains without increasing the inlining or physical-growth budgets.
- Construct fresh whole-local struct call results directly in their destination; preserve snapshots for aliases, exposed addresses, assignments, and cleanup.
- Lower known-zero copies to zero operations and emit exact short x86 zero fills.
- Zero arena storage with aligned native-word stores and exact byte edges; retain public allocation/failure behavior.
- Avoid repeated UTF-8 decoding for ASCII, cache JSON string scan inputs, and copy owned unescaped strings directly.
- Hoist integer overflow thresholds out of digit loops.
- Initialize lazy file-read arenas before capacity checks and use bounded 64-KiB read chunks.
- Recognize only exact, trusted SDK byte-search declarations. Optimized x86 direct calls use bounded SSE2 loads; ordinary function bodies remain for indirect calls, tree emission, and other architectures. A first/last-byte filter avoids pathological candidate rescanning.
- Align optimized x86 function entries and their ELF/COFF/Mach-O text sections to 64 bytes. Debug, DWARF, O1, foreign symbols, source type layout, and calling conventions retain their previous policy.

No benchmark names, paths, checksums, or input-specific dispatch enter the compiler. No external runtime dependency was added. The public JSON Value representation remains unchanged; no pooling prototype was adopted.

## Experiment controls

Linux x86-64 on the recorded Ryzen 9 9950X host. Generic target code, CPU 2, warm filesystem cache, serial runs, two warmups and nine rotating paired samples. Exact application outputs and independent input-derived oracles are mandatory. Sources for the seven application ports remain unchanged. Original input snapshots, binaries, and earlier results are retained.

The JSONL corpus has 60,000 records. Large search covers 1,024 files and 64,292,352 bytes. The source search reuses the immutable 264-file compiler/std snapshot, 3,671,196 bytes. CLI times include startup and I/O. C uses yyjson; Rust uses serde_json. Search-library choices differ, so these are application/library comparisons rather than a universal language ranking.

HTTP compares Dyn, Go, Node and Python std servers on one server CPU, separate client CPUs, new connections, validated JSON responses, five rounds, and one/four-client workloads. No C/Rust server framework was selected. TLS, databases, persistent connections, overload, and multi-core scaling are not covered.

DNA uses the immutable before-this-pass editor and native library against the rebuilt editor/library, five alternating pairs of a two-round workflow, isolated state, and the same observation interposer. Input-update wall time is not key-to-display latency. Small differences and maxima from five samples do not establish tail-latency guarantees.

## Rejected probes and regression diagnosis

The two-pass exact JSON node/string pool preserved the tested ownership, diagnostics, rollback, and ABI, but slowed this JSONL application from 59.569 to 81.230 ms. It remains an isolated artifact.

Last-byte-only SIMD search regressed the common-final-byte/early-prefix-mismatch case from 15.094 to 20.400 ms. The first/last-byte filter reduced that probe to 1.414 ms; it trades a small cost on already-fast large-file search for better behavior across inputs.

A sieve slowdown had an identical 218-byte hot body. A factorial layout probe measured 134.402 ms with 32-byte function alignment, 133.876 ms after data-only alignment, and 123.378 ms with 64-byte function alignment. The old compiler measured about 123.6 ms. Extra global-array alignment was not retained. Function alignment is a general policy, not a sieve-specific special case.

## Evidence and reproduction

The JSON files alongside this report contain all final samples, versions, hashes, commands and scopes. Full logs and rejected probes remain in `build/c-levels-20261024/`; original application inputs remain in `build/app-comparison-20261024/`. Final application outputs are under `build/app-comparison-c-levels-final-20261024/`. DNA evidence is under its sibling checkout’s `build/c-levels-20261024/`.

Use a fresh output directory with `python3 tools/app-comparison/run.py --output build/NEW-NAME`; run no other builds/benchmarks during timing. The retained `final-complete-paired.py`, `compute-complete.py`, and `simd-search-stress-final.py` reproduce the fixed-workload checks using the immutable baselines. Source-search helpers that target the original default directory must not overwrite that snapshot.

Earlier failed attempts remain logged: a stale static byte-store count, stale internal inliner calls, and missing 64-byte COFF/Mach-O metadata. Each was corrected before the fresh final full-suite run. No commits were created. Native macOS/Windows and physical-board performance are not qualified; Win64 search executes under Wine, and embedded correctness uses the existing emulator environment.
