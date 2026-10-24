# Final native performance gap report — 2026-10-25

This pass is complete: it investigates the remaining sorting, scalar UTF-8, points, sieve, and safety-check gaps, retains two bounded improvements, and refreshes the application comparison. It does not establish C-level speed in every area. Both library algorithms and compiler code generation still matter.

[Interactive results](results.html). [All final samples and commands](evidence/final-measurements.json). [Application results](evidence/applications.json).

## Retained changes

1. **`std/sort`: allocation-free introsort.** Three-way median-of-three partitioning, insertion sort for small partitions, a heap fallback, and recursion only on the smaller side. The public API remains unchanged. A monotone-prefix scan returns already nondecreasing input and reverses nonincreasing input. The scan stops when both orders are disproved. Worst-case comparison count is O(n log n), with O(log n) stack. Sorting remains unstable and requires a strict weak `<` ordering; floating NaNs have no defined sort order.
2. **Exact masked-extension simplification.** SSA removes a narrowing/extension only when a constant AND mask proves that it is an identity. Signed forms also require the sign bit to be clear. This removes redundant machine instructions without removing a possible safety failure. The width-64 guard avoids undefined shifts. The instruction improvement is verified, but its isolated runtime benefit is too small to claim here.

The new regressions are registered in `tests/run.py`. Current generics documentation is updated. No safety checks are globally disabled. Experimental compilers and byte-patched binaries are diagnostic artifacts only.

## Final extended workloads

Whole-process median milliseconds; lower is better. Runtime sizes/seeds are opaque to the compilers. Each row uses three warmups and 25 samples per port, serial execution pinned to CPU 2, and deterministic shuffled order. Input generation, allocation, startup and shutdown are included. The round count is eight times the ordinary runner's default to reduce startup noise. Independent Python oracles validate every output.

| Workload | Previous Dyn | Final Dyn | C -O3 | Rust | Go | Final Dyn/C |
|---|---:|---:|---:|---:|---:|---:|
| sort | 123.777 | 83.606 | 138.487 | 15.983 | 88.287 | 0.60× |
| map | 42.558 | 42.659 | 35.452 | 34.334 | 37.264 | 1.20× |
| utf8 | 55.102 | 55.540 | 31.460 | 44.092 | 53.716 | 1.77× |
| allocate | 27.422 | 27.465 | 23.613 | 41.347 | 32.929 | 1.16× |

Sorting compares different libraries/algorithms: Dyn introsort, C qsort, Rust sort_unstable, and Go slices.Sort. Allocation compares arenas/bulk rewind against calloc/free, Rust Box and Go heap/GC; it is not a pure allocator or codegen test. Map uses matched explicit linear probing. UTF-8 uses a matched custom scalar decoder on generated valid Unicode, mostly four-byte sequences; it is not a malformed-input or std Unicode qualification.

The non-sort rows have no clear improvement from this pass. Small differences vary with code layout and the shared desktop host. In particular, the earlier tentative UTF-8 gain did not reproduce in the final cohort. No aggregate speedup score is used.

## Sorting: matched driver, distributions and same-algorithm C

All ports below receive input from the same compiled C-driver source and expose an external sorting entry point. This removes differences in each language's argument parser and input generator. The C `same algorithm` column is a direct u32 translation of the final Dyn introsort, including the monotone scan, partition, depth limit and heap fallback. It passed 1,000 independent Python full-array oracle cases. This is algorithm matching for these valid u32 arrays, not equivalence of the languages' behavior on invalid memory or arbitrary types.

32,768 values, 64 rounds; whole-process milliseconds. Exact input generation, sortedness checks, and independent weighted-sum oracles are shared across each row.

| Input | Old heap | Final intro | C qsort | C same algorithm | Rust sort_unstable | Heap/intro |
|---|---:|---:|---:|---:|---:|---:|
| random | 124.941 | 83.679 | 138.986 | 75.186 | 17.468 | 1.49× |
| sorted | 74.390 | 3.318 | 26.621 | 2.702 | 2.700 | 22.42× |
| reverse | 77.994 | 3.750 | 28.114 | 3.156 | 2.754 | 20.80× |
| equal | 4.832 | 3.414 | 24.683 | 2.839 | 2.734 | 1.42× |
| duplicates | 94.482 | 23.591 | 83.364 | 22.099 | 6.993 | 4.00× |

Random sorting takes about 33% less time; duplicate-heavy input is about 4× faster, and sorted/reversed input over 20× faster than the old heap. The first introsort prototype was slower than heap on sorted/reversed data; that version was not retained. Its measurements and source are preserved in the evidence.

On random input, final Dyn is about 11% slower than the same-algorithm C translation. Rust remains about 4.8× faster in this shared-driver fixture. Therefore the whole Rust gap cannot be assigned to raw Dyn emission: algorithm and library implementation choices remain substantial. Tiny-slice performance and adversarial performance beyond these five distributions were not measured; their correctness and heap fallback were tested.

## Safety-check families

These variants share the same final SDK and benchmark source, using separately frozen pre-fold compiler snapshots. A variant suppresses only the named guard family; `all` additionally suppresses other guards and overflow operations. These are diagnostic interventions, not supported build modes. Bounds/overflow negative controls prove that each selective compiler still rejects the other family's failure.

| Workload | Checked | Bounds suppressed | Overflow suppressed | Pointer/target guards suppressed | Broad suppression |
|---|---:|---:|---:|---:|---:|
| map | 42.651 | 41.789 | 41.701 | 41.240 | 36.338 |
| utf8 | 55.287 | 51.925 | 48.993 | 55.043 | 46.187 |
| allocate | 27.386 | 26.591 | 26.671 | 24.633 | 23.606 |

Pointer/target includes null, alignment and indirect-target guards. Bounds alone are not the explanation for all gaps. Overflow checks matter in the UTF-8 kernel; pointer guards are a useful allocation follow-up. These effects are not additive: suppressing checks also changes CFG shape, optimization opportunities, register choices and layout. The broad probe cannot be interpreted as a fixed language-wide “safety tax.” The original checks remain in production.

## UTF-8: isolated decoder evidence

A shared C driver generates identical input and calls an external decoder. This excludes Dyn's allocation and argument-processing paths from the decoder comparison. C and Dyn use the same u32 accumulator, usize cursor/count, scalar recurrence, and wrapping u64 checksum.

| Decoder variant | Milliseconds |
|---|---:|
| checked-loop | 52.979 |
| fixed-loop | 52.697 |
| nocheck-loop | 55.212 |
| checked-unroll | 39.726 |
| checked-offsetunroll | 37.769 |
| c-common | 29.729 |
| c-no-unroll-common | 42.617 |

GCC expands the bounded continuation loop into straight-line paths; Dyn retains a counter, comparisons, backedge and extra register copies. The GCC no-unroll control changes only the decoder compilation flags and links the exact same driver object. Disabling that expansion raises C time from about 30 to 43 ms. Explicit checked Dyn expansion reduces roughly 53 to 38–40 ms, while preserving the required checks on valid input. It still does not reach C.

This supports loop expansion and subsequent lowering as a material codegen opportunity. It does not prove that general-purpose unrolling is safe or beneficial everywhere. The conditional-count expansion variant in the first cohort did not help. No general loop-unrolling optimizer or specialized benchmark shortcut was shipped.

No hot decoder spills were found: extra register copies and loop state are observed; stack-spill speculation is unsupported for this decoder. The masked-extension fix removes one redundant normalization instruction, but fixed-loop versus checked-loop differs by only about 0.5%, and the application pair below is similarly close. No clear runtime win is claimed. The isolated broad-suppression decoder is actually slower here, another reason not to equate instruction/check removal with guaranteed speed.

## Other native kernels

Final compiler; fixed inputs and complete checksum agreement across ports. Each C column is measured separately. Fixed-input kernels can allow compiler specialization and are not complete applications.

| Kernel | Dyn | C -O2 | C -O3 | Go | Dyn / faster C |
|---|---:|---:|---:|---:|---:|
| fib | 23.917 | 65.828 | 55.481 | 277.938 | 0.43× |
| hash | 77.209 | 77.171 | 77.141 | 77.716 | 1.00× |
| matmul | 51.603 | 58.729 | 58.705 | 109.042 | 0.88× |
| points | 12.240 | 9.847 | 20.809 | 13.864 | 1.24× |
| sieve | 121.527 | 110.938 | 111.004 | 135.452 | 1.10× |

Hash is effectively tied; matmul and Fibonacci favor Dyn on these fixtures. Points remains about 24% slower and sieve about 10% slower than the faster C build.

Points uses the same signed 64-bit work and safe input ranges in both ports. Both already use reciprocal multiplication rather than hardware division. Dyn has redundant aggregate stack traffic and repeated reciprocal setup. Removing the stack traffic in an address-preserving binary probe saves only a few percent; it does not close the gap. Broader scheduling, induction and scalar-forwarding opportunities remain unproven. GCC -O3 interchanges the point/round loops and becomes slower; `-fno-loop-interchange` restores roughly -O2 speed. Comparing only against the worse -O3 result would misleadingly favor Dyn.

Sieve's marking loop is nearly identical to C. Probes folded a byte load/compare, coalesced count copies, changed REP fill width, and combined these changes. None improved the measured workload; some were slower. Those changes were not shipped. The remaining sieve cause is unresolved, rather than established to be bounds checks, zeroing or the number of redundant instructions. Hardware-counter and loop-layout work would be the next useful investigation.

Binary patches are attribution tools only. NOP padding keeps addresses but still changes instruction decoding. Fixture checksum equality is not sufficient proof for a general optimizer.

## Complete application ports

Fresh checked outputs and measurements use the final compiler, ordinary std APIs, and the same independent corpus oracles. JSONL has 60,000 documents; search walks 1,024 generated text files, with defined symlink and binary-file behavior. Nine timed rounds follow two warmups. These are warm-filesystem whole-process CLI runs, including startup and I/O. RSS is median per-process high-water memory, not total system memory.

| Port | JSONL ms | Search ms | JSONL RSS MiB | Search RSS MiB |
|---|---:|---:|---:|---:|
| dyn | 41.087 | 9.985 | 18.0 | 8.1 |
| gcc | 12.315 | 32.462 | 15.4 | 2.3 |
| clang | 12.854 | 31.696 | 15.6 | 2.2 |
| rust | 41.493 | 45.453 | 15.1 | 2.2 |
| go | 186.708 | 13.188 | 48.9 | 13.8 |
| node | 71.508 | 69.578 | 98.5 | 67.3 |
| python | 236.517 | 79.913 | 47.7 | 19.1 |

The same-task JSONL pair is 42.000 ms before masked-extension folding and 41.910 ms after. This does not establish a material speedup from that fold. The faster current JSONL result versus older dated reports includes earlier work and is not credited to this pass.

Dyn JSONL is approximately tied with Rust's serde_json port and 3.34× slower than C/yyjson here. This remains the largest measured application gap. The mutable DOM representations, allocation strategies and parser algorithms differ; this comparison does not isolate codegen. Earlier matched compact-JSON twin reports remain dated evidence and were not refreshed here. Search favors Dyn in these ports, but their directory and substring-search implementations differ.

### Bounded local HTTP

One server CPU, clients on separate CPUs; new connections and 64-document JSON bodies. Five rounds per implementation, each with 100 warmups, 100 single-client samples and 300 requests across four clients. Every response is checked. Across four server ports this is 10,000 validated requests including warmups, plus separate correctness requests.

| Server | Four-client requests/s | Single median ms | Median of round p95 ms | Peak RSS MiB |
|---|---:|---:|---:|---:|
| dyn | 11320 | 0.111 | 0.865 | 18.0 |
| go | 5229 | 0.218 | 1.095 | 17.0 |
| node | 7462 | 0.140 | 1.258 | 70.5 |
| python | 4596 | 0.226 | 1.364 | 21.1 |

Dyn leads these four tested server ports. No C/Rust server framework was included. This is not TLS, database, overload, persistent-connection, multicore-throughput or production-service qualification. Client-side request generation and validation are part of measured wall time.

## Gap inventory and disposition

| Area | Current disposition | Evidence-based next step |
|---|---|---|
| Standard sorting | Improved and retained; random still ~11% behind same-algorithm C and much farther behind Rust | Investigate branch-efficient/specialized partition strategies; preserve generic fallback and worst-case bounds |
| Redundant masked casts | Fixed and retained; instruction reduction proven, runtime gain unproven | Keep regression; do not inflate speed claims |
| Scalar UTF-8 | Material loop-expansion/codegen gap remains | Add bounded loop expansion only with range, order, failure, growth and cross-target proof |
| Allocation | Around 16% behind this C calloc/free workload | Investigate valid nonnull/alignment return facts; preserve failure checks and ownership |
| Linear-probe map | Around 20% behind matched C loop | Study check interactions and register/control-flow lowering; isolated guard effects do not explain the full result additively |
| Points | Around 24% behind faster C flags | Profile induction/scheduling and aggregate forwarding; tested traffic removal alone is insufficient |
| Sieve | Around 10% behind C; causal fix unresolved | Use counters/layout-controlled probes; do not ship the unsuccessful instruction-count changes |
| JSONL DOM application | 3.34× C/yyjson; approximately Rust parity in this port | Refresh compact-reader/twin experiments separately before choosing DOM/library versus compiler changes |
| Search / local HTTP | Competitive in these exact application ports | Extend workload and platform coverage rather than claim a general ranking |
| Cleanup-region sharing | Previously rejected for fork and owner-capacity semantics | Keep registration lifetimes unchanged; no unsafe region optimization restored |

“C speed everywhere” is not achieved and is not a meaningful universal stop condition. The report distinguishes actual measurements, structural code evidence and unresolved hypotheses. It does not treat every C library result as a pure language comparison.

## Qualification and limits

- Strict debug and release compiler builds pass.
- Thirteen nearby regression gates pass, including native SSA across its supported native targets, cleanup proofs, bounds, store forwarding, aggregate returns, optimizer effects, generics, stdlib/performance contracts, formatting, and both new regressions.
- Final sorting passes 756 independent oracle cases in debug, release, forced-tree and forced heap-depth 0/1 modes, plus signed-zero corruption negative controls. It validates exact float-bit permutation separately from numeric order.
- Masked extension passes 52 cases and 520,832 values per SSA/tree mode, with exact positive instruction checks and negative masks/sign-boundary controls. Full-width source tests do not claim constructed SO_EXT64 branch coverage.
- Final sort/mask code cross-compiles to ten native targets, including hard/soft RV32 and Thumb. Cross-compilation is not hardware execution or cross-platform performance qualification.
- Application correctness covers valid/invalid CLI data, normalized outputs, schema boundaries, HTTP routing/malformed/size-limit behavior and clean shutdown. Frozen application sources and compiler hashes remain unchanged during measurement.
- An initial qualification command named a nonexistent `ssa.py`; it was corrected to `native-ssa.py`. The completed 13-gate list is preserved. No compiler failure was hidden.
- No complete repository regression run was performed after these narrow changes. Prior full-suite reports remain separate historical qualification.
- Measurements use one shared Linux Ryzen 9 9950X desktop. Affinity does not remove interrupts, sibling-thread load, frequency, cache, layout or thermal effects. Small percentage differences should not be treated as portable gains.
- This pass does not refresh math transcendental accuracy/speed, DNA input-to-presentation latency, large databases, long-running allocation pressure, TLS, disk-cold behavior, C++/Java/C# ports, other CPUs or physical embedded boards. Those remain coverage gaps, not demonstrated language failures.

## Reproduction and evidence

The live experiment workspace is `compiler/build/final-gap-20261025/`. It contains frozen binaries, before/after source, disassembly, exact build commands and measurement scripts. Source copies of scripts are included here as evidence; their ROOT calculations target that original workspace layout, so moving and executing them unchanged is not a portable runner.

- [Final microbenchmarks and all raw samples](evidence/final-measurements.json)
- [Initial prototype/probe samples, including rejected sorting regression](evidence/measurements.json)
- [Application samples, versions, commands and hashes](evidence/applications.json)
- [Targeted qualification](evidence/qualification.json), [final additional checks](evidence/final-prepare.log), [final ten-target compile log](evidence/checks-final-prepare.log)
- [Sort patch](evidence/sort.patch), [masked-extension patch](evidence/masked-extension.patch)
- [Same-algorithm C sort](evidence/same-algorithm-sort.c), [shared driver](evidence/shared-sort-driver.c)
- [UTF-8 disassembly findings](evidence/decoder-findings.md), [compute findings](evidence/compute-findings.md), [exact byte-patch probes](evidence/binary-probes.json)

Reproduction order: build/check all variants first; freeze artifact hashes; stop other builds/tests; run `measure-all.py` for the initial attribution cohort, `measure-final.py` for final sorting/check cohorts, `measure-remaining.py` for the other kernels, `measure-apps.py` for the application harness, and `measure-app-pair.py` for the isolated application pair. Preserve existing JSON before rerunning: the measurement scripts are experiment scripts, not append-safe benchmark infrastructure. Every case validates output before recording time.
