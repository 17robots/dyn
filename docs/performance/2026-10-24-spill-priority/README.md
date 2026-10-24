# Native SSA spill priority — 2026-10-24

The retained fix protects heavily used values from eviction by cold temporaries. It improves the matched parser and both complete JSON applications on this host. C parity is not reached.

## Change and mechanism

The allocator previously evicted the compatible active interval ending farthest in the future, regardless of its use count. That spilled the parser-state pointer for its entire lifetime and caused repeated stack reloads. The final policy preserves the old farthest-end and lifetime rules, but skips a victim whose weighted uses exceed four times the incoming value's uses. Uses inside loops cost 4^depth, capped at depth 5. This is a static heuristic, not profile-guided allocation.

Register classes, clobber restrictions, hints, spill storage, rematerialization, callee saves, language checks and ABIs remain unchanged. The extra compiler work is a linear operand walk and eight bytes per SSA value. No compile-time or compiler-memory speed claim is made.

Product changes: `src/backend/ssa.inc` and `tests/ssa-loop-constants.py`. Std/parser source is unchanged. A more aggressive least-used-victim experiment was rejected after a repeatable file-search slowdown; its results remain under `build/spill-priority-20261024/absolute-timing.json`.

## Final paired measurements

Milliseconds; lower is better. Relative change compares medians.

| Workload | Before | After | Time change |
|---|---:|---:|---:|
| Matched parser | 21.571 | 17.243 | -20.1% |
| Compact JSON application | 37.423 | 34.313 | -8.3% |
| Mutable JSON application | 56.951 | 52.444 | -7.9% |
| Large-directory search | 12.360 | 12.488 | +1.0% |
| Project-directory search | 5.775 | 5.927 | +2.6% |

Checked GCC takes **12.337 ms** for the same parser, leaving Dyn at **1.398×** its time. The complete C+yyjson application takes **14.216 ms**, versus **34.313 ms** for Dyn compact JSON. Those complete applications use different parsers; their gap cannot be assigned entirely to code generation.

See [raw timings](timings.json) and [paired bootstrap intervals](confidence.json). Search differences require interpreting those intervals; no search speedup is claimed when the interval includes 1.

## Controls and correctness

- All **208/208 registered gates passed**, zero skips, on the final policy. Source/test/tool/runtime hashes remained unchanged throughout qualification and final measurements. [Qualification](qualification.json), [source hashes](source-hashes.json).
- The allocator regression keeps a repeatedly used long-lived parameter in a register. The saved old allocator fails its new assertion with exit 6. Synthetic no-control/no-operand fields are explicitly initialized, preserving the original constant-rematerialization assertions.
- All 1,828 frozen parser cases match before/after in both scanner modes, including failures, values, offsets and allocation/helper traces.
- Every one of 60,000 corpus documents matches the checked-C normalized DOM and traces in both modes: [proof](corpus-proof.json). The original [matched-parser report](../2026-10-24-json-twins/README.md) documents the independent oracle and safety differences.
- Final independent static review found no concrete issue. No new sanitizer qualification is claimed.

## Method and limits

Generic release x86-64, optimization level 3, no cache. CPU affinity 2; serial timings with no concurrent builds/tests. Rotating/reversing order, two warmups, 17 retained samples per JSON/parser variant and 41 per search variant. Parser samples run three corpus passes; reported time is per 60,000-document pass. Input loading and library/arena setup precede the parser clock. JSON application/search measurements include process execution. Exact report/search outputs are checked every time.

The two parser implementations retain the same algorithm, 16-byte values, layout and shared primitive implementations. Safety instrumentation is not instruction-identical to C. Shared helpers and their time remain included.

Compiler SHA-256: `6b8f780d19f2bea52f78c2fdef5b1a0189f59bc03727905c160b24d21957fd58`.

Evidence and executable paths: `compiler/build/spill-priority-20261024/`; full per-gate logs are in its `qualification/` directory. [Source diff](ssa.diff), [measurement script](measure.py). The scripts use retained benchmark inputs described in the matched-parser report.

These are selected host workloads, not a universal language ranking. Redundant branches, other spill/reload costs and the remaining parser gap are still open. DNA has not been rebuilt or timed in this pass. Other targets received regression coverage, not this performance qualification.
