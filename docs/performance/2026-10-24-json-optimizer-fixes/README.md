# JSON and compiler optimization fixes, 2026-10-24

Three measured paths are improved: exact dominating unsigned bounds, expensive
loop constants, and compact JSON ASCII string scanning. The existing mutable
JSON implementation and DNA source are unchanged. No safety mode is disabled.
General loop auto-vectorization and the remaining yyjson gap are not resolved.

## Retained changes

- `ssa_prove` recognizes an exact `index < length` fact from a dominating branch,
  including reversed operands and false edges. It does not infer through signed
  comparisons, changed operands, arithmetic or phi inputs. Independent interval
  analysis previously lost this relation when the upper bound was dynamic.
- x86 SSA can retain one expensive integer constant bit pattern per function
  when repeated loop operands justify it. LICM and CSE share its materialization;
  normal interval/clobber allocation handles calls. An evicted or unallocated
  constant rematerializes instead of acquiring a spill slot. The demonstrated
  integer loop now materializes its u64 limit once before the loop, rather than
  twice in each digit path.
- The private `ascii_string_prefix` helper in `std/encoding/json/read` has a
  bounded SSE2 implementation on optimized x86. It stops before controls,
  non-ASCII bytes, quote or backslash. The existing decoder processes that byte,
  escapes, UTF-8, and errors. Loads never cross the slice end and need no aligned
  input. Only the exact SDK declaration and signature acquire the derived
  intrinsic identity; other targets and tree emission use the scalar body.

The SIMD change is a narrow library fast path. It does not make arbitrary Dyn
byte-classification loops vectorized, nor accelerate the mutable JSON reader.

## Qualification

The final source passes **208/208 registered gates, zero skips**, in one
uninterrupted run. All **669 source/runtime/test/tool hashes** remain identical
before/after qualification and through final measurements. Both compiler builds
pass. Static independent reviews report no remaining concrete findings in the
bounds proof, constant handling or SIMD helper.

New registered regressions prove check removal and required failures, constant
materialization, deterministic register eviction/rejection, all byte classes,
odd slices, guard-page ends, live floating values and local lookalike behavior.
Existing compact-reader checks pass all eight RV32/Thumb hard/soft debug/release
guests, retaining soft instruction audits. A separate deterministic 1,500-case
parser acceptance/rollback check passes debug and release. Supplementary
Windows/Wine SSA and tree executions pass; the constant-eviction harness also
passes ASan/UBSan.

## Final measurements

Same fixed 60,000-record JSONL input and exact application output oracle. Generic
x86-64 O3, CPU 2, serial builds/tests/measurements, rotating/reversing order,
11 measured samples after two warmups. Input SHA-256 remains
`55632bc536a41285c2126eb1a0d684fc6778c303b95bdf380e9c3f8b509abfca`.

| Full application | Before | After |
|---|---:|---:|
| Compact read-only Dyn DOM | 40.311 ms | 36.924 ms |
| Mutable Dyn DOM | 56.359 ms | 57.683 ms |
| GCC + yyjson comparator | 13.485 ms | unchanged binary |

Compact runtime falls **8.4%**; paired bootstrap time-ratio interval is
0.8842–0.9205, using 10,000 resamples of these finite same-host samples.
The C application remains **2.74x faster**. This does not establish C parity or
an inherent language performance ceiling.

The mutable result triggered a longer follow-up rather than a dismissal. In
17 additional rotating samples, mutable medians are 56.639 ms before, 56.035 ms
with all changes, and 56.089 ms with constant retention disabled. The initial
approximately 2% slowdown does not repeat, and disabling retention does not
improve it. Earlier paired results also fluctuated. There is **no consistent
mutable-reader timing change**, so no mutable speedup or proven slowdown is
claimed. Every measurement window is retained.

The longer follow-up independently measures compact 40.339 to 36.759 ms, an
8.9% reduction; disabling retention gives 36.955 ms. Preliminary ablation gives
40.402 ms before, 37.510 with SIMD alone, 39.358 with compiler fixes alone and
36.952 combined. Ablation supports retaining both paths; these layout-sensitive
variants are not an exact additive cycle attribution.

Large-directory search medians are 9.951 to 9.826 ms. The immutable project
snapshot is 5.426 to 5.387 ms. These small differences do not establish a search
speedup. No DNA rebuild or responsiveness claim is part of this pass.

## Matched kernels and parser isolation

Kernel rows contain different repeat counts and must not be added together.
Checked C preserves arithmetic overflow checks on valid benchmark accesses; it
does not have the full Dyn pointer/slice failure contract.

| Kernel | Before Dyn | After Dyn | Checked C | Ordinary wrapping C |
|---|---:|---:|---:|---:|
| Byte classification, 10 repeats | 80.956 ms | 65.970 ms | 52.752 ms | 15.144 ms |
| Integer scanning, 5 repeats | 38.212 ms | 34.657 ms | 35.072 ms | 15.953 ms |
| Selected records, 20 repeats | 6.944 ms | 6.983 ms | 3.725 ms | 5.463 ms |

The integer kernel now matches checked C within this measurement's variation.
The generic byte kernel remains scalar and still trails vectorized ordinary C.
Record traversal is effectively unchanged. These kernels are evidence about
specific generated loops, not a language ranking.

Under the identical C line driver, five passes of DOM-only parsing improve from
146.632 to 128.949 ms; yyjson takes 23.733 ms. That remaining approximately 5.4x
region gap still mixes parser design, allocation and generated code. Shared
wrappers differ from full applications; do not subtract these times from the
application medians.

Additional valid parser shapes all pass their independent checksums:

| Shape, 200,000 parses | Before | After |
|---|---:|---:|
| Short object | 15.366 ms | 14.964 ms |
| Short ASCII string | 6.566 ms | 6.199 ms |
| Escaped string | 26.229 ms | 23.808 ms |
| Unicode string | 46.113 ms | 45.737 ms |
| Long ASCII string | 101.273 ms | 35.672 ms |

These finite samples do not guarantee every input improves. SIMD is retained
because it improves the complete application as well as these parser fixtures.

## Evidence and reproduction

[Summary](summary.json), [qualification](qualification.json),
[every registered gate](qualification-results.json), [source hashes](source-hashes.json),
[final applications](final-apps.json), [kernels](final-kernels.json),
[search](final-search.json), [common-driver parsing](final-parser.json),
[constant follow-up](constant-ablation.json), [parser shapes](shapes.json),
[preliminary ablation](ablation.json), and [supplementary checks](extra-proof.json).

Exact workspace drivers, binary identities, before snapshots, generated probes,
disassemblies, randomized cases and full logs remain under
`compiler/build/json-optimizer-fixes-20261024/`. The earlier
[isolation report](../2026-10-24-json-language-isolation/README.md) describes the
kernel contracts and common C harness. No canonical application sources or fixed
inputs are overwritten. No new dependencies are installed.

Run registered regressions with `python3 compiler/tests/run.py` in a provisioned
environment. Focused new gates are `ssa-loop-bounds.py`, `ssa-loop-constants.py`,
and `json-ascii-prefix.py`; the last explicitly skips hosts other than Linux x64.
The full qualification used the existing Podman QEMU wrappers and cached Unicorn
package. Other-platform speed and physical-board behavior remain unqualified.
