# JSON loop follow-up and rejected optimizer trials — 2026-10-26

The retained product change makes this JSONL report about **4.6% faster** than
PR139 by simplifying private whitespace and digit loops. It does not change the
public API, mutable DOM, number text, ownership, zeroing, error offsets, depth
limit, or rollback. The new grammar regression is registered in tests/run.py.

This investigation deliberately does **not** ship register coalescing, broader
loop hoisting, multiplication rewrites, or an application numeric shortcut.
Fewer instructions did not reliably mean faster programs.

## Accepted library change

`skip` snapshots its private cursor's source/offset and classifies the same four
ASCII whitespace bytes directly. Three digit loops use their exact predicate
without calling a helper. Other callers retain the existing helpers. The source
is byte-identical to the measured combined probe (SHA256
`bf466a6d2aed93f01d4541751f0db1346fb0c1167566bc8d32f84b021809c552`).

The original controlled trials isolate skip, digit, and combined changes:

| JSONL implementation | Median ms | Paired ratio versus baseline |
|---|---:|---:|
| Baseline | 39.691 | 1.0000 |
| Local whitespace cursor/predicate | 39.278 | 0.9907 |
| Direct digit predicates | 38.472 | 0.9677 |
| Combined, retained | 37.953 | 0.9554 |
| Parse-first numeric shortcut, rejected | 39.901 | 1.0046 |

[Raw trials](initial-trials.json). The changes also affect inlining decisions;
this is a whole-source intervention, not a pure count of helper-call cycles.
The simpler numeric shortcut was correct on the tested boundary cases but did
not improve runtime, so no application or std numeric API change is included.

A second independent timing window confirms the combined result:
39.633 ms baseline, 37.834 ms current, paired ratio **0.9540**, bootstrap 95%
interval **[0.9517, 0.9581]**. Do not combine percentages or absolute times with
other dated reports as if they were one simultaneous run.

## Existing read-only DOM: a separate application choice

The report only reads input DOMs. An isolated application variant uses existing
`std/encoding/json/read` for that input, while keeping mutable JSON for output
and leaving the HTTP service unchanged. It fully parses/materializes ignored
fields; it is not a schema scanner or typed-deserialization shortcut.

| JSONL implementation | Median ms |
|---|---:|
| Prior mutable DOM | 39.633 |
| Mutable DOM with retained loop change | 37.834 |
| Existing compact input DOM | 27.621 |
| Retained GCC C/yyjson application | 13.137 |

The compact variant takes about 30% less time than the prior mutable app and
27% less than the updated mutable app here, while still taking about 2.10 times
the C/yyjson time. This is an API/representation comparison, not isolated
language overhead. The fixed 60,000-record, 13,589,721-byte corpus has identical
independent summary outputs. Forty-four numeric/parser/schema cases are retained
in [edge controls](compact-edges.json).

**The APIs have different contracts.** Mutable number text can represent an
ignored `1e309`; compact rejects it as NumberOverflow. Compact owns all text;
mutable number text borrows input. The experiment preserves and explicitly tests
that difference rather than changing either policy. No product application
switch is made by this patch. The exact alternative source is
[compact-input-main.dyn](compact-input-main.dyn), with commands/hashes in
[compact-build.json](compact-build.json) and corpus identity/output in
[compact-corpus.json](compact-corpus.json).

## Rejected compiler candidates

| Candidate | Observed trade-off | Decision |
|---|---|---|
| Bounded postallocation GPR coalescing | Full UTF-8 workload about 0.4% faster, build cost about 9–11% higher; sort about 0.4% slower | Keep out of product |
| Exempt rematerialized constants from loop dependencies | Map about 5.3% slower; allocation about 3.8% slower | Keep current hoister |
| Unsigned power-of-two MULO/MULH shift lowering with relaxed fixed clobbers | Map about 5.8% slower, despite faster JSON/search samples | Keep current multiply lowering |
| Same shift lowering with original clobbers retained | Map about 1.2% slower | Reject this variant too |
| Exact-layout removal of one redundant map load | About 0.2% gain | Insufficient justification for a broad load-CSE change |

The arithmetic and hoist probes pass independent numerical, panic/cleanup,
operand-order and zero-trip controls. Those are correctness results, not speed
proofs. The arithmetic prototype's intermediate signed-MULH clobber mistake was
caught by the points oracle and fixed before measuring the frozen candidate.
No such code was applied to product sources.

The old map high multiply is blocked from hoisting by a loop-local rematerialized
constant. Removing that artificial dependency is mathematically valid, but the
resulting whole program was slower. Register pressure, placement, and target
costs need evidence before a profitability policy can improve it. Preserving
original clobbers reduces the shift variant's regression, consistent with an
allocation contribution; it does not isolate the entire cause. An exact-layout
arithmetic patch could not preserve both required results within the available
16 bytes (minimum 18), so no unsafe binary control was attempted.

The earlier standalone coalescing kernel gained about 2.7%; that did not transfer
to a comparable gain in the complete workload. Broad compile/runtime checks
therefore changed the decision. The experiment also permits macOS x86-64 in its
guard; only Linux was execution-qualified. It remains entirely outside product.

## Method and evidence

All timings are serial, Linux x86-64, pinned to CPU 2, warm filesystem cache,
three warmups plus 25 recorded randomized samples. Every successful output is
checked, and binaries are hashed before/after runtime measurements. Dyn uses
release O3, generic CPU and no cache. Paired compiler experiments use the same
source, project/SDK paths, flags and frozen noncompiler objects. Application and
kernel commands/hashes are embedded in the raw JSON. Compile-cost comparisons
use three warmups and 15 recorded cache-disabled full builds, with identical
source/SDK/output paths and only the compiler variant changed.

- [Initial runtime trials and all variants](initial-trials.json)
- [Hoist/arithmetic/compact follow-up trials](followup-trials.json)
- [Whole-build cost](compile-cost.json)
- [Arithmetic with original clobbers](original-clobbers.json)
- [JSON source and binary identities](json-build.json)

The reference compiler is parent139 `59104604d621995de0b4f3327b010b0df9ded593`,
SHA256 `e19afab4b479c86a18b36f27367bf51dc6f1646a768e1acdb26a5dbcafe25377`.
Current product changes are confined to JSON source and tests; no register or
hoist experiment is part of this patch.

## Qualification and remaining gaps

The new suite passes debug/release and default/forced-tree modes: all 256 byte
classifications at prefix/suffix/numeric boundaries, exact number tokens,
malformed-number tokenizer progress, error kind/detail/offset, usable failure
stub, rollback, 262-KiB whitespace and 64-KiB numeric bounds. The frozen baseline
passes the same semantic checks. Existing JSON string/read and parser-contract
regressions pass. Eight additional RV32/Thumb hard/soft debug/release guests pass
with the new scalar-loop fixture; soft images pass no-FP audits.

Static independent review found no correctness issue. Full repository CI remains
a separate gate before merge. These measurements do not establish universal
C parity or production latency guarantees. Dyn already has useful desktop/CLI
performance in the measured workloads; whether it is fast enough depends on the
application's latency, throughput and memory budget.

The remaining high-value work is a profitability model for code motion/register
choices, JSON representation/conversion costs, and the larger scalar UTF-8 gap.
The measured C/yyjson gap is not evidence that every Dyn program has that cost.
