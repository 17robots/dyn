# Measured compiler/library improvements and broader comparisons — 2026-10-24

This pass improves specific compiler and compact-JSON paths, extends safe byte-count vectorization, and refreshes the language/application comparisons. It does not establish universal C parity or imply that every remaining performance opportunity is fixed.

[Interactive comparison](results.html). Raw data and qualification evidence are linked below.


Follow-up: [bounded hot-loop inlining](../2026-10-24-hot-loop-inlining/README.md) further reduces allocation/UTF-8 call overhead. This report retains its original compiler snapshot.

## Retained changes

- **Loop proofs:** eliminate a conditional check when the exact unsigned relation is already established by a dominating edge. Checks lowered through cleanup paths now benefit too. Only the current branch control is replaced, preserving comparisons shared by CSE; existing folding repairs CFG/PHIs. No speculative arithmetic or signed-range extrapolation is added.
- **Register allocation:** keep the existing farthest-end eviction policy first. When that would spill a hotter incoming long-lived interval, allow it to replace a compatible interval with strictly less than one quarter of its use weight. Register classes, clobber constraints, spill slots and ABI preservation remain unchanged.
- **Byte loops:** reuse loaded SIMD data and use saturated subtraction for unsigned thresholds, reducing instruction overhead. Extend bounded O3 x86-64 counting from `==`/`<` to `!=`/`>=`, including up to three OR terms. Exact 16-byte extents, scalar tails, precise near-overflow behavior, private-counter and work-budget restrictions remain. This is a bounded pattern extension, not arbitrary vectorization.
- **Compact JSON:** already-validated string keys use the string decoder directly rather than recursively redispatching through the general value parser. Allocation, ownership, error offsets, rollback and depth policy remain unchanged; public API and value layout do not change.

- **Expression inlining:** extend bounded expansion through unconditional first-evaluated arithmetic/conversion spines and safely captured assignment targets. Preserve sibling effects, conditional evaluation, packed alignment, panic/check origins and the existing per-caller growth/resource caps. Unsupported forms retain calls.
- **IR loop identities:** compact sparse loop IDs after expansion, preserving FOR/BREAK/CONTINUE identity and the established IDs-below-statement-count invariant. This fixes a Wasm compiler crash uncovered by broad qualification. A deterministic negative control and 30 complete browser-Wasm repeats cover the failure. Before the final SDK-path normalization, 12 native benchmark binaries are checked byte-for-byte across this fix and remain identical; the controlled final programs are then rebuilt under the staged SDK path.
- **Typed arrays:** perform the same checked byte-size calculation in the typed wrapper, exposing constant element sizes before ordinary arena allocation. Zero-count bypass, overflow/exhaustion diagnostics, zeroing, events and cleanup are preserved.

The byte emitter gets smaller as well as faster. A separate placement experiment reproduces the former record regression using identical normal-path instructions. No speculative global padding policy is added. Startup is freshly measured below; no new startup-specific optimization is claimed.

Product files are `src/backend/ssa.inc`, `src/native_opt.c`, `std/mem/mem.dyn`, `std/encoding/json/read/read.dyn`, their focused tests/registration, and new benchmark tool `tools/bench/extended.py`. Existing unrelated working-copy changes are preserved. [Source diff](source.diff).

## Final paired before/after measurements

Milliseconds; lower is better. Before is the previously qualified codegen-followup compiler. Both versions are rebuilt from frozen project sources at identical project/SDK paths with no cache. Before uses the original SDK; final uses the current SDK, including compact-key and typed-array changes. [Build environments and SDK hashes](build-environments.json) document both builds. Relative change compares medians. Paired bootstrap intervals are final/before time and include host noise, not uncertainty over all possible programs.

| Workload | Before ms | Final ms | Time change | Paired 95% ratio |
|---|---|---|---|---|
| Byte predicate scan | 10.075 | 8.511 | -15.5% | 0.842–0.847 |
| Integer parsing | 30.212 | 30.476 | +0.9% | 0.981–1.030 |
| Record traversal | 7.566 | 6.957 | -8.1% | 0.910–0.936 |
| JSON line processing | 236.336 | 229.249 | -3.0% | 0.962–0.975 |
| Matched JSON parser | 17.185 | 17.108 | -0.5% | 0.983–1.002 |
| Compact JSON application | 33.462 | 32.802 | -2.0% | 0.974–0.984 |
| Mutable JSON application | 50.596 | 49.019 | -3.1% | 0.966–0.972 |
| Large-directory search | 10.423 | 10.580 | +1.5% | 1.005–1.052 |
| Project-directory search | 5.460 | 5.379 | -1.5% | 0.975–0.997 |
| New >=128 byte count | 58.576 | 6.289 | -89.3% | 0.103–0.111 |

Matched checked-C parser: **12.337 ms**, final Dyn **17.108 ms** (**1.387× C time**). The same-algorithm parser gap remains. JSON line processing instead calls different Dyn/yyjson parsers; its gap mixes implementation, allocation and code generation. “Checked C” means the fixture's arithmetic checks, not all Dyn pointer/slice/diagnostic contracts. No across-workload aggregate score is used.

Read [raw timings](final-timing.json), [intervals](confidence.json), and the [new predicate experiment](complement-timing.json). Small differences whose intervals include 1 do not establish a change. The large-search median is slightly slower in this run; that regression is retained in the table rather than excluded from the report.

## Fresh six-language, seven-toolchain compute sweep

Whole-process milliseconds, fixed sources/checksums. Compilation is excluded. Both Dyn versions are freshly rebuilt from frozen sources under identical paths: original compiler/SDK before, final compiler/SDK after. The five compute fixtures do not use the changed JSON reader. Integer checking and startup/allocation choices differ between ports; floating multiplication contraction is disabled for C. No NumPy, BLAS or other substitute algorithm/library is used.

| Kernel | Before Dyn | Final Dyn | GCC | Clang | Rust | Go | Node | Python |
|---|---|---|---|---|---|---|---|---|
| fib | 24.182 | 24.162 | 55.866 | 159.476 | 159.003 | 279.793 | 552.477 | 5437.824 |
| hash | 76.932 | 76.809 | 76.899 | 76.489 | 76.632 | 77.431 | 4138.519 | 5652.141 |
| matmul | 51.511 | 51.571 | 57.685 | 115.501 | 117.078 | 111.990 | 136.769 | 7182.865 |
| points | 12.210 | 12.210 | 20.800 | 12.345 | 12.588 | 13.854 | 85.802 | 994.517 |
| sieve | 130.925 | 129.791 | 111.439 | 110.256 | 111.318 | 129.449 | 200.884 | 6693.073 |

These are selected kernels, not a general language ranking. C appears twice (GCC and Clang); that is seven toolchains across six languages. Frozen sources, exact commands, versions and binary hashes: [manifest](languages-manifest.json). [Every sample](languages-results.json).

## Broader native workloads

Whole-process milliseconds, including setup/input generation/shutdown. Runtime sizes and seeds are opaque to each compiler; independent Python oracles check every result.

| Workload | Before Dyn | Final Dyn | C | Rust | Go |
|---|---|---|---|---|---|
| sort | 49.039 | 17.281 | 18.735 | 3.324 | 12.762 |
| map | 72.188 | 7.465 | 5.800 | 5.627 | 6.347 |
| utf8 | 47.176 | 47.302 | 5.871 | 7.282 | 8.784 |
| allocate | 99.060 | 99.466 | 4.386 | 6.497 | 5.643 |

- Sorting intentionally compares different standard algorithms: Dyn heap sort, C qsort, Rust unstable sort, Go slices.Sort.
- Map tests use a matched explicit linear-probe table with duplicate keys/collisions and consumed lookups, not each language's standard map API.
- UTF-8 uses a matched custom decoder on valid mostly-four-byte text. It does not qualify malformed-input handling or std Unicode performance.
- Allocation compares different lifetime/allocator policies: Dyn arena bulk rewind, C allocation/free, Rust Box, Go heap/GC. Untouched interior zero stores may be optimized differently. It is not a pure allocator/codegen comparison.

The new inlining removes the generator calls from sorting and map loops. Three generator calls remain in the allocation/UTF-8 branches with protected-call overhead; structural eligibility is satisfied, and per-caller budget/resource rejection is the strongest static explanation, not a separately isolated timing cause. No growth cap was raised to force them through. Allocation and UTF-8 results must therefore not be described as fixed.

Only one generated distribution is covered. Checksums validate output, not every intermediate operation. No RSS measurement is collected for these four kernels. [Manifest and precise limits](extended-manifest.json), [samples](extended-results.json), [durable runner](../../../tools/bench/extended.py).

## Complete applications and bounded HTTP

Fresh CLI application ports; milliseconds and peak process RSS MiB. These Dyn rows use the mutable std JSON API. The compact-reader application is measured separately in the paired table above. C uses yyjson; Rust uses serde_json; libraries/search algorithms differ.

| Port | JSONL ms | Search ms | JSONL RSS | Search RSS |
|---|---|---|---|---|
| dyn | 48.414 | 10.506 | 18.0 | 8.1 |
| gcc | 12.591 | 32.707 | 16.0 | 2.2 |
| clang | 13.228 | 32.885 | 15.6 | 2.3 |
| rust | 41.758 | 45.810 | 15.0 | 2.2 |
| go | 186.278 | 13.193 | 49.0 | 13.9 |
| node | 70.847 | 68.999 | 98.4 | 68.6 |
| python | 237.386 | 79.114 | 47.6 | 19.1 |

HTTP uses a single server CPU, separate client CPUs, new connections, 64-record JSON bodies, validated responses and five rounds. Each server round performs 100 warmups, 500 single-client samples and 1,000 four-client requests: 1,600 requests per round, 32,000 across four languages. This is a bounded sustained run, not overload/TLS/database/persistent-connection/multicore qualification. C/Rust server frameworks are not included. Client validation overhead is included.

| Server | Requests/s | Single median ms | Four-client p95 ms | Peak RSS MiB |
|---|---|---|---|---|
| dyn | 10751 | 0.120 | 1.150 | 18.0 |
| go | 5226 | 0.221 | 1.103 | 17.0 |
| node | 11112 | 0.122 | 0.606 | 87.9 |
| python | 4618 | 0.227 | 1.345 | 21.2 |

[All CLI/HTTP samples, checks and versions](applications.json). HTTP p95 values are descriptive for this finite run, not tail-latency guarantees.

## Startup and compiler-cost controls

Empty-report execution includes process startup, file I/O, initialization and serialization; it is not pure runtime startup. Milliseconds:

| Port | Median ms |
|---|---|
| dyn | 1.295 |
| gcc | 1.377 |
| clang | 1.383 |
| go | 2.104 |
| rust | 1.462 |
| node | 14.393 |
| python | 26.970 |
| before | 1.442 |
| compact | 1.291 |

No-cache compiler build wall time, same current SDK for both compiler versions, same CPU. This separates compiler cost from library source changes; it is not a cross-language compiler-speed comparison. Milliseconds:

| Project | Before | Final |
|---|---|---|
| parser | 10.862 | 11.284 |
| compact | 62.208 | 64.468 |
| mutable | 50.666 | 52.274 |

Compile-time medians are about 3–4% higher for these three projects, a measured tradeoff of roughly 0.4–2.3 ms; these build timings have no confidence interval.

Complete binary sizes are coarse controls, not isolated hot-code size. No universal growth bound is inferred from these examples.

| Compute binary | Before bytes | Final bytes | Change |
|---|---|---|---|
| fib | 45240 | 44856 | -0.8% |
| hash | 45240 | 44920 | -0.7% |
| matmul | 45624 | 45304 | -0.7% |
| points | 45440 | 45056 | -0.8% |
| sieve | 45264 | 44880 | -0.8% |

[Startup samples](startup.json), [compile samples](compile-timing.json). No startup improvement is claimed from small unqualified differences.

## Code placement control

The prior record function is cloned into fresh RX mappings at several offsets. Its entire normal path stays byte-identical; only cold RIP-relative pointers/calls are relocated. The two tested placements with a 4-KiB-crossing hot loop are slower than the nearby noncrossing placements. This isolates a placement cost in this fixture, while branch/front-end alignment factors can still contribute; it is not a guarantee that every page crossing is slow. No invalid-input/unwind relocation contract is claimed for this experimental clone harness.

| Function offset | Hot loop crosses 4 KiB | Median ms |
|---|---|---|
| 0x700 | False | 7.161 |
| 0xe00 | False | 7.029 |
| 0xf00 | False | 7.111 |
| 0xf80 | True | 7.728 |
| 0x1700 | False | 7.079 |
| 0x1f00 | False | 7.056 |
| 0x1f80 | True | 7.731 |

[Placement bytes/addresses and samples](record-layout-control.json), [control harness](record-layout-control.py). The final paired record result above determines whether the tested application regression recovered; the control does not promise layout-independent performance.

## Correctness, qualification and limits

- Final compiler passes **214/214 registered gates, zero skips**, in one final run. Debug/release builds and all registered artifacts/executions pass. Earlier attempts stopped at a now-inlined-symbol test assumption and the sparse-loop-ID Wasm crash; both were corrected before the final complete run. [Qualification](qualification.json), [every gate](qualification-results.json), [source/test/tool/runtime hashes](source-hashes.json).
- Cleanup-proof tests preserve exact SSA/tree values, status and cleanup/panic traces. Hot-interval tests cover strict thresholds, existing-hot protection and clobber rejection.
- All 19 byte-count fixtures pass SSA/tree/O2, all-byte/length/offset/page-end/near-overflow checks and Win64 Wine execution. Inverse predicates preserve precise overflow behavior. Other targets retain their existing scalar lowering.
- Compact JSON tests cover ownership, rollback, exact invalid-key metadata, maximum-depth keys and scalar values; host tree/SSA and eight RV32/Thumb hard/soft guests pass, including soft instruction audits.
- Saved baseline compiler/emitter fails the original three codegen controls and nested-expression call removal: [negative controls](negative-controls.json). The library refactor intentionally preserves existing semantics.
- All 1,828 frozen translated-parser cases match checked C in both scanner modes. All 60,000 corpus documents match exact normalized output/traces in both modes: [case proof](verification.json), [corpus proof](corpus-proof.json).
- Expression-inlining tests preserve target-before-RHS failures, sibling effects, conditional evaluation and packed-field stores in SSA/tree modes. Typed-array tests compare original/untyped contracts across dirty buffers, alignment, events, poison/reuse, zero count and exact failure messages.
- Before expression inlining, existing comparison binaries remained byte-identical across the inverse-predicate extension: [binary control](inverse-common-binary-equivalence.json). The later expression-inlining and typed-array changes are rebuilt and timed separately in the final measurements. Independent static reviews found no concrete remaining correctness issue. The bounded expression/resource/loop-identity harness also passes ASan/UBSan; no whole-compiler sanitizer qualification is claimed.

Runtime support object bytes are held fixed across comparisons: [hashes](runtime-object-hashes.json). Benchmark processes run serially on the recorded Linux Ryzen 9 9950X host. No correctness tests or unrelated builds run concurrently with timings; application ports are built before their own timing phase. Native CPU affinity is 2; HTTP clients use separate CPUs. The host is an ordinary desktop, not otherwise idle or frequency locked. Rotating/reversing order, warmups and repeated samples reduce, but do not eliminate, noise. Paired parser/kernel and compact/mutable application runs use 25 samples; search/startup controls use 41. The separate seven-port CLI sweep uses nine samples, HTTP five rounds, and compiler-cost controls 13 samples. The compute sweep uses 18 native and four Node/Python samples; extended native workloads use 15. Bootstrap uses 10,000 resamplings and no multiple-comparison correction. Work amounts differ across rows and must not be summed.

Fresh benchmarks identify remaining gaps rather than proving every area solved. Remaining map/UTF-8 work, sorting algorithm choices, parser design and code generation need separate experiments. The new workloads exposed real gaps; the final table reports them without a universal language score. Bounds/overflow checks remain enabled; no benchmark-specific dispatch or new dependency is introduced. Physical-board, native Windows/macOS performance and DNA interaction latency are not measured in this pass.

Evidence and reproduction scripts are retained under `compiler/build/performance-inline-20261024/`. Frozen inputs/helper libraries come from the earlier [matched-parser experiment](../2026-10-24-json-twins/README.md). Runtime scripts are local evidence, not a standalone benchmark distribution.

Final compiler SHA-256: `11d472944f13982100f2d1167c00adfeed956493e01dca5afd2c3bd8e9e1d224`.
