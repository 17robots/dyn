# Allocation follow-up: bounded hot-loop inlining — 2026-10-24

The remaining random-generator calls in the allocation batch were rejected by the inliner's cost budget. This follow-up verifies that cause, changes admission priority within the existing limits, and removes those calls. It does not change the arena algorithm or establish C-level allocation speed.

[Interactive comparison](results.html).

## Cause and retained fix

An isolated instrumented compiler reports only **3 cost units remaining** when it reaches the allocation generator helpers. Each requires **15 units**; **1,854 resource units remain**. This is cost-budget starvation, not a source-language inability to inline the calls. [Before trace](inlining-before.log), [after trace](inlining-after.log).

The optimizer now reserves allowance for eligible small direct calls observed in original caller loops. The bounded scan shares the existing unconditional-expression-spine rules; it excludes deferred/conditional RHS calls, recursion, foreign/variadic calls, preserved byte intrinsics and unsupported depths. Failed scans reserve nothing.

- O3 totals stay **512 cost / 4,096 resources per live caller**.
- Reservation is at most **128 / 1,024**, taken from those totals.
- Candidate callee cost is at most 16; scan work is capped at 4,096 visits, traversal depth 64, actual call credit depth 16, and expression spines 32 wrappers.
- Cold expansions cannot spend reserved allowance. Original loop-site expansions debit both the reservation and ordinary totals; newly exposed nested calls cannot steal that reservation.
- O2 is unchanged. A retained O2 fixture and an O3 no-loop fixture are byte-identical before/after.
- Panic guards, overflow checks, target evaluation order, packed alignment, lexical cleanup and dense loop IDs retain the existing behavior.

No function names, benchmark modes or allocation sizes are singled out. Product changes are in `src/native_opt.c`, a focused regression and registration. [Product diff](source.diff), [focused evidence](reservation-evidence.json).

## Fresh allocation/UTF-8 and control workloads

Milliseconds, lower is better. All native ports run serially on CPU 2: two warmups, 15 retained rotating/reversed samples. Independent Python oracles check every output. Runtime sizes/seeds are opaque. Both Dyn versions use the same project/SDK paths and unchanged SDK; before is the previous qualified compiler. C/Rust/Go ports are freshly built before timing.

| Workload | Before Dyn | Final Dyn | Change | C | Rust | Go | Paired 95% ratio |
|---|---|---|---|---|---|---|---|
| sort | 17.609 | 17.583 | -0.1% | 19.090 | 3.568 | 12.996 | 0.987–1.006 |
| map | 7.824 | 7.882 | +0.7% | 6.011 | 5.881 | 6.804 | 0.980–1.025 |
| utf8 | 49.799 | 17.226 | -65.4% | 6.191 | 7.896 | 9.448 | 0.344–0.352 |
| allocate | 101.184 | 37.933 | -62.5% | 4.576 | 6.905 | 6.188 | 0.365–0.375 |

Allocation improves **2.67×**, but final Dyn still takes **8.29× C time** in this fixture. UTF-8 improves **2.89×**, with **2.78× C time** remaining.

The allocation fixture performs 32 batches of 8,192 64-byte blocks: 262,144 allocations, 524,288 generator calls before inlining, plus reads and arena rewinds. Before has three static generator call sites (two allocation, one UTF-8); final has zero. [Call proof](call-proof.json).

This is **allocation plus setup/generation/cleanup**, not raw arena throughput. C allocates/frees blocks, Rust uses Box, Go uses heap slices/GC, and Dyn rewinds an arena. Zero initialization can be optimized differently. Sorting compares different standard algorithms. Map uses matched linear probing; UTF-8 uses matched custom valid-input encode/decode, not the full std Unicode implementation. No RSS is measured for these four kernels. Exact sources, commands, versions, sizes, seeds, checksums and hashes: [manifest](extended-manifest.json), [samples](extended-results.json), [intervals](extended-confidence.json).

The policy also changes other cold inlining decisions, so the full time difference cannot be assigned exclusively to removal of generator-call overhead. Generator-call removal is established directly; total timing gains are measured separately.

## Other paired workloads

Same frozen parser/kernel/application inputs and expected outputs as the [previous pass](../2026-10-24-performance-expansion/README.md). These compare the previous compiler to this follow-up, not the original pre-improvement baseline. Milliseconds:

| Workload | Before | Final | Change | Paired 95% ratio |
|---|---|---|---|---|
| parser | 17.521 | 17.388 | -0.8% | 0.989–1.000 |
| scan | 8.755 | 8.645 | -1.3% | 0.984–0.999 |
| integers | 32.425 | 31.808 | -1.9% | 0.947–1.016 |
| records | 7.189 | 7.258 | +1.0% | 0.974–1.032 |
| parse_lines | 235.604 | 235.701 | +0.0% | 0.996–1.008 |
| compact | 34.705 | 34.291 | -1.2% | 0.971–1.002 |
| mutable | 51.045 | 50.366 | -1.3% | 0.978–0.995 |
| large-search | 12.450 | 12.911 | +3.7% | 0.980–1.039 |
| project-search | 5.831 | 5.766 | -1.1% | 0.953–1.031 |

Parser/kernels and JSON applications use 25 retained samples; searches use 41. Bootstrap intervals use 10,000 resamplings without multiple-comparison correction. Small differences with intervals spanning 1 do not establish improvement/regression. The prior matched-parser gap remains; JSON-line processing still compares different Dyn/yyjson implementations. “Checked C” checks fixture arithmetic, not every Dyn pointer/slice/diagnostic contract. [Raw measurements](primary-results.json), [intervals](primary-confidence.json).

## Compiler-cost control

No-cache build wall time, same current SDK/project paths and CPU 2; 13 retained alternating samples per compiler/project. These are build costs, not runtime performance or a cross-language compiler comparison. Full raw data is retained below.

| Project | Before ms | Final ms | Change |
|---|---|---|---|
| parser | 12.176 | 12.061 | -0.9% |
| compact | 67.639 | 67.441 | -0.3% |
| mutable | 55.176 | 55.489 | +0.6% |

[Compile samples](compile-timing.json). No confidence interval is claimed for these build controls.

## Qualification and remaining work

- **215/215 registered gates pass, zero skips**, in a complete final run. Source/std/runtime/test/tool hashes stay unchanged throughout qualification. [Summary](qualification.json), [each gate](qualification-results.json), [hashes](source-hashes.json).
- Focused tests cover late-loop admission, unchanged no-loop/O2 behavior, bounded scans, quota caps, exact resource debits, nested-loop quota isolation, recursion, excessive depth, conditionals, deferred captures, overflow/check origins and cleanup. The saved old compiler fails the late-loop call-removal assertion. The focused C harness passes ASan/UBSan; no whole-compiler sanitizer qualification is claimed.
- Complete extended binary size changes from 71968 to 72248 bytes. This is a coarse fixture control, not a universal machine-code size guarantee.
- The remaining allocation typed-wrapper call requires 49 growth units; at that site the final trace has 36 total units with 30 reserved for the two generator calls. It therefore remains a real call. Genuine allocator failure paths still require cleanup; no blanket nonpanic exemption is introduced.
- The remaining allocator call chain, result handling, and zeroing/validation paths need a separate experiment. UTF-8 retains a C gap. No claim of universal C parity, full allocator optimization, or improved DNA interaction latency is made.

Runtime timings use the recorded Linux Ryzen 9 9950X host, CPU 2, after all focused tests/builds finish and before broad qualification starts; no tests/builds run concurrently with timing. The desktop is not frequency locked or otherwise guaranteed idle. Full qualification subsequently verifies the same frozen source/compiler state. Compiler-cost controls run separately after qualification, with no other tests/builds active. No new cross-language HTTP, native Windows/macOS performance or physical-board qualification is claimed.

Evidence/reproduction artifacts remain under `compiler/build/hot-inline-20261024/`. Benchmark sources are generated by [extended.py](../../../tools/bench/extended.py). Runtime/parser helpers come from the retained earlier experiments; these local scripts are not a standalone benchmark distribution.

Final compiler SHA-256: `4a8ce93949e0309b26944f523cc4f3c046e9e28433a9b2bef45763f589943bc3`.


## Subsequent runtime follow-up

The [2026-10-25 unwind-slot investigation](../2026-10-25-unwind-slot-hints/README.md) isolates cleanup lookup overhead and adds validated lookup hints. It reports a further allocation gain and small measured CLI JSON regressions; this report retains its original compiler/runtime snapshot and measurements.
