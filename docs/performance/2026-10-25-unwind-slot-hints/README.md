# Allocation follow-up: validated unwind-slot hints — 2026-10-25

**Allocation improves substantially, but final CLI JSON controls regress 0.6–1.3%; this is not a universal performance win.**

[Interactive comparison](results.html).

The largest remaining cost in the allocation batch was thread-slot lookup for panic cleanup. This pass changes that runtime lookup, preserving the existing allocation source, zero initialization, failure checks, and cleanup. It does not change the allocator, compiler inlining budgets, or generated application IR.

## Measured product result

Fresh whole-process timings on the recorded Linux Ryzen 9 9950X host, pinned to CPU 2. Two warmups, 21 retained rotating/reversed samples per binary; every output matches an independent integer checksum. No builds/tests run concurrently with timing. The desktop is not frequency locked.

| Allocation workload | Before Dyn | Hint Dyn | C calloc/free | Improvement | Paired 95% final/before ratio |
|---|---:|---:|---:|---:|---:|
| 32 × 8,192 blocks | 42.208 ms | 17.511 ms | 4.737 ms | 2.41× | 0.371–0.468 |
| 128 × 8,192 blocks | 171.712 ms | 69.071 ms | 15.393 ms | 2.49× | 0.367–0.449 |

The first row is the same workload size as the [previous report](../2026-10-24-hot-loop-inlining/README.md). Its old 37.933 ms measurement is not substituted for the fresh 42.208 ms baseline. Dyn remains **3.70× C calloc/free time** in the fresh 32-batch comparison. This is an allocator/library comparison, not a pure language comparison: Dyn rewinds an arena, while C frees separate zero-initialized blocks.

The workstation developed substantial unrelated browser CPU load during the later windows. Absolute times vary across windows, including both baselines and C controls. The table uses only the final paired window; preliminary windows are retained separately. These intervals describe that sampled desktop session, not an idle-machine speed guarantee.

The timed compiler binary is unchanged from the prior report. Only the runtime object changes. Both before/after programs compile the same source with the same compiler, SDK and release/O3/generic flags. Timings include process startup, argument parsing, RNG, block writes, checksum reads, and cleanup; they are not raw allocator throughput. [Measurements](measurements.json), [manifest](manifest.json), [Dyn workload](workload.dyn), [C calloc workload](calloc-workload.c).

## What isolated the cause

The first diagnostic API probes use 128 batches. Typed push, direct arena push, and uninitialized push take approximately 137, 137, and 133 ms. Omitting zeroing does not recover most of the gap. A diagnostic version without deferred release takes approximately 14 ms, but loses cleanup on failure and is not a retained fix.

The unchanged old runtime obtains the current thread identity, then searches up to 64 owner slots before claiming an empty one. Each scanned slot invokes an atomic-load helper. A protected allocation repeats this registration after the previous call unregisters its frame.

A separate C arena control uses the **actual same Dyn set/link/unlink runtime**, around a noinline checked zeroing allocation call. Fresh 128-batch paired measurements:

| Control | Old runtime | New runtime |
|---|---:|---:|
| C arena, same cleanup runtime | 159.225 ms | 52.963 ms |
| Dyn std arena, unchanged workload | 171.712 ms | 69.071 ms |
| C arena, no panic protection | 4.562 ms | — |

C's simpler arena does not reproduce std/mem's complete metadata, validation or observable diagnostics. This control measures successful cleanup registration; its failure handling is not a complete C implementation of Dyn defers. The control demonstrates that the runtime overhead also appears in C; it does not establish equal compiler output or universal language parity.

Additional diagnostic binary patches isolate the old successful single-thread path: replacing thread identity with a constant leaves about 106 ms; bypassing the slot search leaves about 22 ms. These patches are unsafe for production threads/panics and remain **diagnostics only**. Their differences are not additive cost accounting. An outlined Dyn source variant preserves outer cleanup and takes about 13 ms, but changes function boundaries and optimizer decisions; it is not used as the reported product result. [API/source probes](api-probes.json), [cleanup diagnostics](cleanup-isolation.json), [C control](matched.c).

## Retained runtime change

The original one-read fast path for a current owner in slot zero stays ahead of the hint lookup. An initial candidate did not preserve it: fresh JSON app controls measured roughly 2–3% regressions. The retained version restores the path and reuses its owner read when validating a slot-zero hint. A separate read-count assertion rejects the initial candidate.

A 64-entry hint table stores a full eligible thread identity and six-bit slot index in one atomic word. Every lookup still obtains the current thread identity. A matching hint must validate the slot's atomic owner, or successfully claim an empty slot atomically. Collisions, occupied stale hints, and missing hints use the existing complete search. Identities outside the nonzero 58-bit packing range use that search without truncation.

Hints do not own slots, extend lifetimes, raise the 64-active-owner limit, or suppress failure cleanup. The original search updates a hint only after finding or claiming the real slot. A thread's own matching hint therefore names its most recently known slot; other identities can only evict that hint. Atomics preserve the existing ownership publication/release ordering. Shared-runtime contexts, target register banks and native ABI layouts are unchanged. The table adds 512 bytes of static storage per linked runtime context.

The regression counts atomic reads rather than noisy elapsed time. One thousand repeated empty-stack link/unlink pairs require at most 2,100 reads, compared with 64,000 in the old implementation. It also checks exact identity-call counts, nesting, register canaries, colliding threads, oversized identities, capacity, release and reuse. The old implementation fails the empty-stack read-count assertion; the initial hint candidate fails the one-read nested-owner assertion. [Source diff](source.diff).

## Qualification

- **215/215 registered gates pass; zero skips** in a complete run against the final version, after the nested-path refinement. Source/std/runtime/test/tool hashes remain unchanged throughout and still match at publication. [Summary](qualification.json), [each gate](qualification-results.json), [source hashes](source-hashes.json), [run log](qualification.log).
- All **552 embedded cleanup guests pass** on hard/soft RV32 and Thumb, preserving exact traces/status, named SSA selection, ABI/snapshot/guard behavior, and soft no-FP checks. [Focused guest log](embedded-cleanup.log); the full run independently repeats this gate.
- Native focused tests pass: owner hints/collisions/oversized identities/capacity, exact identity calls, nonvolatile registers, panic-message lifetime, runtime support, synchronization and networking. The original source fails the empty-stack read bound; the initial candidate fails the nested one-read bound. [Focused verification](focused-verification.json).
- Twelve additional target runtime-support objects cross-build successfully. [Target list](cross-builds.json). The default runtime artifacts are rebuilt; the timed candidate object exactly matches the installed x86-64 runtime object. Compiler executable bytes remain unchanged.
- The initial candidate also passed a separate full suite, but was refined after the application controls caught its regression. That earlier pass is not substituted for the final run.

Independent read-only review found no concrete correctness issues in the hint/ownership change. Runtime thread identities must remain unique among concurrent threads, as required by the existing implementation. Single-hart bare-metal atomics retain their existing limitations. Native Windows/macOS runtime behavior is not established by cross-links or Linux ABI harnesses.

## Application controls and the remaining tradeoff

Two frozen CLI JSON report applications use the same compiler, SDK, source paths, input and expected semantic output as before. Only the linked runtime changes. After final qualification, 41 retained rotating/reversed samples plus two warmups per executable run serially on CPU 2. Every output matches the frozen reference. The C control uses yyjson and a different implementation; it is not an algorithm-matched language comparison.

| CLI report | Before Dyn | Final Dyn | Change | C/yyjson | Paired 95% ratio |
|---|---:|---:|---:|---:|---:|
| compact JSON | 32.561 ms | 32.972 ms | +1.3% | 13.554 ms | 1.012–1.017 |
| mutable JSON | 48.133 ms | 48.408 ms | +0.6% | 13.638 ms | 1.003–1.009 |

These are **small measured regressions**, not gains or proof of unchanged performance. The allocation benefit is retained with this explicit tradeoff. Restoring the one-read nested path reduces the initial candidate's additional lookup work; it does not establish zero cost in complete applications. Linked code/layout changes can also affect performance, and their contribution has not been isolated here. An isolated cold-helper extraction did not remove the small app regressions and is not retained. No source outlining, safety removal or benchmark-specific padding is introduced in the product.

[Final app samples](app-controls.json), [earlier v2 window](app-controls-first-v2.json), [rejected initial candidate](initial-candidate/app-controls.json), [unretained extraction probe](thin-probe-app-controls.json). Initial v1 and preliminary v2 measurements remain distinct from final qualification and final 41-sample app controls. No multiple-comparison correction or idle-machine guarantee is claimed.

## Remaining gap

A current-thread identity syscall still occurs for every protected link on Linux. Set/link/unlink calls, result preservation and allocator wrapper/metadata work also remain. The data does not justify removing panic protection or declaring allocator throughput equivalent to C. A broader optimization would need to reduce repeated cleanup registration while preserving capture timing, checked failures, nested defers, thread identity and foreign callbacks.

No full application/DNA latency improvement, global language ranking, native Windows/macOS performance, physical-board execution or RSS claim is made. The prior source-level benchmark and earlier reports remain unchanged. Local experiment scripts are retained under `compiler/build/allocation-isolation-20261025/`; copied scripts here document the procedure and expect that workspace layout rather than providing a standalone distribution.
