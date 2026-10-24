# Safety-check suppression measurements, 2026-10-25

These are native x86-64 microbenchmarks, not an application or language-wide ranking. No product source or compiler binary was changed during this measurement pass. The separate throwaway compiler suppresses selected SSA check operations, overflow operations, cleanup-aware check branches, and tree guards. It is not a supported unsafe mode, and the experiment does not establish that every check or safety-related cost was removed.

Both Dyn builds use identical benchmark source and the current SDK. Compiler and artifact hashes, SDK hashes, complete raw samples, commands and runnable measurement scripts are preserved under `compiler/build/check-cost-20261025/`. The checked compiler SHA256 is `043587f3e272e1aa73453e43d8ef928e669f6d340a8177a277ec3461d8925948`.

## Extended workloads

Whole-process wall time in milliseconds. Each workload uses eight times the original round count, three warmups and 25 samples per port. Execution order is shuffled deterministically, with serial execution pinned to CPU 2. Outputs are checked on every execution against independent Python oracles. C uses GCC -O3, Rust uses opt-level=3, and Go uses its default optimized build with GOMAXPROCS=1.

| Workload | Checked Dyn | Suppression probe | C | Rust | Go | Probe time reduction |
|---|---:|---:|---:|---:|---:|---:|
| sort | 124.075 | 113.268 | 138.422 | 15.932 | 88.172 | 8.7% |
| map | 42.362 | 35.961 | 35.141 | 33.369 | 36.880 | 15.1% |
| utf8 | 54.495 | 46.778 | 31.235 | 41.854 | 53.250 | 14.2% |
| allocate | 27.338 | 23.513 | 23.408 | 40.542 | 32.499 | 14.0% |

Sorting compares different algorithms: Dyn heapsort, C qsort, Rust sort_unstable and Go slices.Sort. Allocation compares different allocator and release policies: Dyn arenas, C calloc/free, Rust Box and Go heap slices/GC. These two rows cannot isolate language code generation. Map uses matched explicit linear probing. UTF-8 uses matched scalar decoding of generated valid input, without malformed-input validation in any port.

## Fixed-input kernels

Times below come from the 25-sample main run. A separate 15-sample interleaved run remeasured checked Dyn and both C -O2/-O3 builds. Both C flag results are shown explicitly; selecting only -O3 would misleadingly favor Dyn on points.

| Kernel | Checked Dyn | Suppression probe | C -O3 | Go | Follow-up Dyn | Follow-up C -O2 | Follow-up C -O3 |
|---|---:|---:|---:|---:|---:|---:|---:|
| fib | 24.023 | 16.428 | 55.441 | 280.526 | 23.687 | 64.968 | 54.844 |
| hash | 76.664 | 76.556 | 76.606 | 76.998 | 76.428 | 76.421 | 76.414 |
| matmul | 51.438 | 51.566 | 58.634 | 108.742 | 50.741 | 57.786 | 57.589 |
| points | 12.211 | 11.911 | 20.895 | 13.796 | 12.091 | 9.697 | 20.651 |
| sieve | 121.379 | 121.222 | 111.092 | 137.384 | 121.194 | 110.532 | 110.430 |

Every execution agreed across ports on its checksum. These fixed inputs can permit compiler specialization; checksum agreement is not proof of equivalent generated work. Whole-process times include startup and shutdown. The shared desktop host was not isolated, and affinity does not eliminate frequency, interrupt or sibling-thread effects.

## Findings and next targets

1. Check suppression reduces map, UTF-8 and allocation elapsed time by about 14–15% in these workloads. This intervention changes control flow and code layout as well as removing checks; it does not isolate bounds checks alone.
2. The map and allocation probes are approximately at their C baselines. This suggests an opportunity for better safe check proofs and lowering, not a justification to remove checks from production.
3. UTF-8 remains approximately 50% slower than C even in the suppression probe. Checks do not explain that remaining gap; the next investigation should compare scalar loop instructions and register use.
4. Points remains about 25% slower than the faster C -O2 baseline in the follow-up. Sieve remains about 10% slower than C. Suppression changes neither enough to explain the gaps.
5. Hashing is effectively tied with C. Matrix multiplication and Fibonacci are faster in these particular fixtures; this is not a universal claim about their algorithms or language implementations.
6. Sorting is principally a library/algorithm investigation: removing selected checks saves only about 9%, while Rust's different sort is about 7.8 times faster than checked Dyn in this fixture.

No new compiler speedup is claimed or installed. The checked compiler hash remained unchanged. No full regression suite was necessary or run for this measurement-only pass.
