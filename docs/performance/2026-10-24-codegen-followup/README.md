# Comparison, spill and byte-loop code generation — 2026-10-24

This pass retains three narrow x86-64 optimizations. Byte scanning and integer parsing improve on this host. The full matched parser remains short of C performance. A record microbenchmark slows down in a combined library despite byte-identical normal-path instructions; that regression remains visible below.

## Retained changes

1. Reuse integer comparison flags across an empty fallthrough block with exactly one predecessor, identical SSA operands and no intervening emitted instruction. Swapped immediate operands retain the corresponding condition. Joins, changed operands and emitted effects prevent reuse.
2. Compare a spilled integer left operand directly against an allocated right register. This removes a scratch reload for that form. Immediate and two-spill forms retain their existing paths.
3. Recognize a bounded forward loop that counts a byte predicate into a private `u64` or `usize` accumulator. At O3 on x86-64, use SSE2 for exact 16-byte chunks and a scalar tail. Predicates admit up to three equality/unsigned-less-than constants joined with OR. The source must cover the full declared slice extent; calls, effects, partial ranges, escaping or modified control locals and pending cleanup decline the shortcut.

The vector path uses no bytes beyond the slice. Near accumulator overflow it resumes scalar execution, preserving the original failing increment and diagnostic instead of reading ahead. The invariant traversal has a shared 4,096-node work bound. Other targets and unsupported shapes retain their existing lowering. This is not a general-purpose vectorizer.

Product files: `src/backend/ssa.inc`, three new regression scripts, and their registration in `tests/run.py`. Std and parser source are unchanged. The prior [spill-priority fix](../2026-10-24-spill-priority/README.md) is present in both before and final compilers.

## Final measurements

Milliseconds; lower is better. Time change compares medians. The interval is a paired bootstrap interval for final/before time, not a confidence bound on all programs.

| Workload | Before | Final | Time change | Paired ratio, 95% interval |
|---|---:|---:|---:|---:|
| Byte predicate scan | 68.212 | 10.343 | -84.8% | 0.148–0.153 |
| Integer parsing kernel | 37.343 | 31.713 | -15.1% | 0.822–0.857 |
| Record kernel, combined library | 7.224 | 8.133 | +12.6% | 1.065–1.162 |
| Line parsing kernel | 249.172 | 243.821 | -2.1% | 0.972–0.990 |
| Matched full JSON parser | 17.579 | 17.463 | -0.7% | 0.987–1.007 |
| Compact JSON application | 34.657 | 34.057 | -1.7% | 0.976–0.992 |
| Mutable JSON application | 52.415 | 52.045 | -0.7% | 0.985–0.999 |
| Large-directory search | 11.630 | 11.571 | -0.5% | 0.976–1.021 |
| Project-directory search | 5.858 | 5.906 | +0.8% | 0.955–1.052 |
| Record kernel, isolated control | 7.147 | 7.176 | +0.4% | 0.981–1.019 |

The matched checked-C parser takes **12.541 ms**; final Dyn takes **17.463 ms**, or **1.392×** its time. This pass does not close that gap. The complete C+yyjson application takes **13.973 ms**, versus **34.057 ms** for Dyn compact JSON. Those complete applications use different parser implementations; their difference is not a pure language/codegen comparison.

All kernel C/checked-C timings, application timings, and individual samples are retained in [raw measurements](final-timing.json). Read [paired intervals](confidence.json) before interpreting small application/search differences; an interval including 1 does not establish an improvement or regression here. No aggregate score or universal C-parity claim is made.

The line-parsing kernel calls Dyn's compact JSON reader versus C's yyjson implementation. Its roughly 5.1× gap against checked-arithmetic C mixes line scanning, parser design, allocation and generated code; it is not a matched-algorithm compiler comparison. Likewise, “checked C” refers to the fixture's arithmetic checks, not an implementation of every Dyn pointer, slice and diagnostic contract. The separately translated full JSON parser is the stronger compiler-isolation experiment.

## Record regression and layout control

The combined-library record kernel takes **7.224 → 8.133 ms**. Its first 207 bytes, covering the entire normal path, are identical. Adding/changing preceding code moves its function from `0x21f00` to `0x21f80`. The hot loop consequently crosses the `0x22000` code-page boundary in the final library. Both hot loops have the same cache-line alignment. [Byte/address proof](record-layout.json).

Compiling that exact record function alone produces **binary-identical before/final libraries**, also timed above. This narrows the difference to the combined build/layout rather than changed record instructions. It does not prove that the page boundary alone causes the slowdown, nor erase the combined-library regression. Layout/front-end sensitivity remains open; no speculative global alignment change is included.

## Experiments rejected

- Higher-level unsigned range merging and recovery of interval facts: stronger integer-kernel results, mixed parser/application results.
- Folding spilled operands against immediates: repeated compact-application slowdown of about 4% in the subset experiment.
- Replacing ordinary subtraction with LEA: no reliable complete-workload benefit.

Their sources, compiler probes and paired exploratory measurements remain under `build/codegen-followup-20261024/ablation-*.json` and the corresponding logs. They are not in the retained compiler. These exploratory runs selected the final candidate; the table above comes from a separate final run.

## Correctness and qualification

- **211/211 registered gates pass, zero skips**, in one final run. This includes artifact construction and all registered executions. Source/test/tool/runtime hashes stay unchanged throughout qualification and final measurements. [Summary](qualification.json), [source hashes](source-hashes.json). Per-gate logs remain under `build/codegen-followup-20261024/qualification/`.
- Comparison tests check 3,073 values in SSA/tree modes, threshold instruction counts, exact short-circuit effects, and negative controls for changed operands, emitted effects and joins.
- The spill-emitter harness executes 34,560 flag checks across 240 forms, including signed/unsigned conditions, high registers, immediates and safe two-spill fallbacks.
- Byte-count tests cover all byte values, overlapping predicates, lengths/offsets, guarded page tails, live FP values, repeated loops, precise overflow and rejection cases. Win64 SSA/tree execution also passes via Wine. The invariant-proof resource rejection has a dedicated control.
- The saved old compiler/emitter fails all three optimization assertions. [Baseline controls](negative-controls.json).
- All 1,828 frozen parser cases match checked C in both scanner modes: [case proof](verification.json). Every one of 60,000 corpus documents matches the prior normalized DOM/failure/trace digest in both modes: [full-corpus proof](corpus-proof.json).
- Final test programs are byte-identical to the retained `lean` probe after rejected experiments are removed: [equivalence](retained-program-equivalence.json). Independent static review reports no concrete remaining finding. No new sanitizer qualification is claimed.

## Method, reproduction and limits

AMD Ryzen 9 9950X, Linux x86-64, generic CPU, O3 release, no cache. All benchmark processes run serially with CPU affinity 2, after builds/tests finish. This is a normal desktop host, not an otherwise idle or frequency-locked laboratory machine. Rotating/reversing order and paired samples reduce, but do not eliminate, host-load and layout effects.

Each variant gets two warmups followed by 25 retained parser/kernel/application samples, or 41 search/isolated-control samples. Every sample checks its exact checksum or complete output. Parser timing includes shared helpers, with tracing disabled symmetrically, and excludes input/library/arena setup; three passes are normalized per 60,000 documents. Application/search measurements include process execution. Bootstrap uses 10,000 resamplings, fixed seed, no multiple-comparison correction.

The full-parser experiment preserves matching algorithms, 16-byte values and shared primitives; safety instrumentation is not instruction-identical to C. See the [matched-parser contract](../2026-10-24-json-twins/README.md). These are selected host workloads. Other targets receive regression coverage, not performance qualification. DNA is not rebuilt or timed in this pass. Remaining parser costs, general vectorization and layout sensitivity remain open.

Final compiler SHA-256: `e19240933ee9c4d15804f31c0f1a1cb6ba2764d0dd7de92f388e752796dafdbc`. [Binary hashes](binary-hashes.json), [source diff](ssa.diff).

Reproduction uses retained frozen inputs and libraries described in the matched-parser report:

```sh
VARIANTS=before,final python3 compiler/build/codegen-followup-20261024/prepare.py
python3 compiler/build/codegen-followup-20261024/verify-final.py
python3 compiler/build/codegen-followup-20261024/measure-final.py
```

Run qualification with the established embedded wrappers/Unicorn environment before measurements. [Qualification driver](qualify.py), [preparation](prepare.py), [proof script](verify-final.py), [measurement script](measure-final.py). Evidence depends on retained build artifacts and is not a standalone benchmark distribution.
