# Matched C/Dyn parser twins, 2026-10-24

**Current Dyn code generation is part of the measured slowdown.** A complete
algorithm-matched parser takes 21.463 ms in Dyn versus 12.611 ms in checked GCC C
and 12.756 ms in checked Clang C: approximately **1.7x slower** for Dyn on this
case. Different JSON algorithms cannot explain this matched comparison.
This is not a proof that the language has an unavoidable performance ceiling.

## What was copied

This experiment makes a literal C translation of the complete parser core from
Dyn's compact read-only reader. It does **not** port yyjson to Dyn. Translating
our entire reader into C gives a tractable, auditable same-algorithm test;
comparing it with yyjson alone would retain the original algorithm confound.

The twins preserve the recursive parser, branches, number token scanning, escape
and surrogate handling, Unicode validation policy, depth limit, error cursor,
node growth, owned input, in-place decoded strings, and arena rollback. Values
are the same contiguous 16-byte `{tag,bits}` records. Object keys remain records;
duplicates and source order are preserved. Every document is fully materialized,
including ignored fields. No schema-specific shortcuts are used.

Both twins call the **same compiled C implementations**, with matching external
call boundaries, for allocation/rewind, input copy, UTF-8 validation, binary64
conversion, and ASCII scanning. All the remaining parser core is compiled by
its respective compiler. The scanner has shared scalar and SSE2 modes. This
isolates parser-core emission; it does not test the quality of Dyn implementations
of those shared primitives or remove every possible language-semantic difference.

Both use the same aligned, preallocated contiguous arena, 32 initial node slots
for containers, geometric in-place growth, and tail trimming. Both wrappers take
an explicit Result output pointer. Portable std error categorization is removed
from both experiment wrappers; syntax detail and exact byte cursor remain.
The experiment ABI is intentionally narrower than the std API. Full field/layout
mapping is in [the mapping note](sources/dyn-mapping.md).

## Functional and work equivalence

Before timing, the twins agree on:

- **1,828 varied inputs** with an independent Python oracle checking acceptance
  and every normalized DOM record: full tags, numeric bits, decoded string/key
  bytes and subtree spans. Lexical numeric tokens and duplicate object keys are
  preserved by the oracle. Depth, malformed/truncated tokens, signed zero,
  numeric boundaries, surrogate pairs, invalid UTF-8 and storage growth are included.
- Exact C/Dyn failure detail and offset, arena offset/peak, allocation sizes,
  allocation/rewind event sequences, helper call counts and helper input sizes.
- **All 60,000 corpus documents**, each containing 25 DOM records, in scalar and
  SSE2 modes. The full normalized output, allocation traces and primitive counts
  match byte-for-byte. These are 1.5 million DOM records per corpus pass.
- Nine initial compiler variants in two scanner modes: **32,904 full case
  comparisons**. Additional C controls, uninstrumented helpers, 16 backing-store
  misalignments, failure stubs and input-alias boundaries also pass.
- Checked C plus its helpers and harness pass ASan/UBSan on all 1,828 inputs;
  normalized output remains identical. Dyn machine code is not sanitizer-instrumented.

Actual x64 layout checks confirm Value 16, Arena 64, Cursor 32, Parser 88 and
Result 48 bytes. Exact normalized corpus output has SHA-256
`fbfbec133aec898a13c602b2f553be93b1449a8a2cbde0d08358fcb2c6d68985`.
The fixed input hash remains
`55632bc536a41285c2126eb1a0d684fc6778c303b95bdf380e9c3f8b509abfca`.

This is finite equivalence evidence, not a formal proof for all inputs. The
independent oracle establishes successful DOM semantics and acceptance; it does
not independently establish every library-specific failure offset. Exact offset
agreement is a C/Dyn translation check.

## Safety controls

Dyn keeps its ordinary checked arithmetic, bounds checks, pointer checks and
explicit `#wrap` operations. The checked C build adds arithmetic-overflow,
indexed-access, slice-order, null and alignment checks at corresponding accesses;
original explicitly wrapping arithmetic remains wrapping. The ordinary C control
uses unsigned wrapping arithmetic.

Checked C is a close source-contract control, **not a claim that both compilers
emit identical checks**. C does not duplicate every Dyn struct-member guard or
narrowing check, and optimization can eliminate different checks. This test
therefore measures generated code and check optimization together, not a pure
register-allocator penalty. Comparing checked and unchecked C is not an exact
estimate of what disabling Dyn checks would save.

An additional conservative C control checks parser/cursor pointers at internal
entries, disables strict-aliasing assumptions, disables interprocedural constant
propagation, keeps frame pointers, and disables deletion of null-pointer checks.
It does not close the gap. These flags are controls, not recommended production
settings or an additive breakdown of optimizer costs.

## Measurements

One Linux x64 host, generic x86-64 O3, CPU 2. Builds, validation and timings run
serially. Input loading, dynamic loading, arena allocation and locale setup occur
before the clock. A single C driver splits the same bytes with `memchr` and calls
each parser. DOM normalization and output serialization are outside timing.
Each measured sample parses the 60,000-record corpus three times and checks
180,000 roots; times below are divided by three. The final follow-up uses
17 rotating/reversing samples after two warmups.

| Matched complete DOM parser | Median per pass |
|---|---:|
| Dyn, ordinary safety checks | **21.463 ms** |
| GCC C, checked | **12.611 ms** |
| Clang C, checked | **12.756 ms** |
| GCC C, conservative checked control | **12.153 ms** |

Dyn/checked-GCC ratio is **1.702**; a paired bootstrap interval from these finite
samples is **1.653–1.751**, using 10,000 resamples. Conservative C gives a 1.766
ratio. An earlier independent window reproduces the approximately 1.7–1.8x gap.

The main 13-sample run also tests primitive and compiler controls:

| Variant | Shared scalar scanner | Shared SSE2 scanner |
|---|---:|---:|
| Dyn | 22.668 ms | 21.447 ms |
| GCC ordinary unsigned C | 12.379 ms | 11.683 ms |
| GCC checked C | 13.607 ms | 12.264 ms |
| GCC checked, vectorization disabled | 14.278 ms | 12.648 ms |
| Clang checked C | 14.477 ms | 12.819 ms |
| GCC checked, strict aliasing disabled | 14.506 ms | 12.869 ms |
| GCC checked, constant propagation disabled | 13.530 ms | 12.260 ms |
| GCC checked, frame pointers retained | 14.436 ms | 13.239 ms |

Headline measurements preload an **uninstrumented** version of the common
helpers, removing diagnostic counters and allocation-trace hashing. The parser
binaries are identical between traced and uninstrumented runs. Independent case
validation confirms that the uninstrumented helpers preserve full DOM,
diagnostics, arena offset and peak. The traced control measures 21.711 ms for Dyn
and 13.135 ms for checked GCC, so tracing does not explain the gap.

The corpus makes zero decimal-conversion calls: its numbers are exact integers.
Floating forms are functionally verified but floating-conversion throughput is
not measured by this corpus. Counts per timed three-pass sample match across all
traced twins: 360,000 pushes, 180,000 rewinds, 180,000 input copies, 120,000 UTF-8
validations, and 2,880,000 ASCII-prefix calls.

These are parsing-region times under controlled wrappers. They must not replace
or be subtracted from earlier whole-application/yyjson measurements, which use
different wrappers and implementations. This experiment does not benchmark a
matched yyjson algorithm.

## Concrete emission differences

Independent disassembly review finds specific missed optimization opportunities:

- Dyn's `read_number` repeatedly reloads the same state pointer from a stack slot.
- It saves more registers and reserves a larger frame than checked GCC.
- Its digit/threshold paths contain duplicate comparisons, extra branch jumps
  and phi-register moves. GCC folds some range tests into one unsigned comparison.
- GCC creates depth-specialized `read_value` clones. Disabling that optimization
  still leaves a substantial C advantage, so cloning alone is not the explanation.

These are observations, not a cycle attribution or a claim that one patch will
recover the entire gap. Register allocation/spill decisions, redundant loads,
branch simplification and check elimination are concrete next targets. Parser
algorithm improvements can help separately, but cannot dismiss this result.

No compiler, std, runtime, test runner or DNA product files changed. All 669
previously qualified product hashes remain unchanged. The full repository suite
was not rerun for this artifact-only experiment.

## Evidence and reproduction

[Summary, versions and hashes](summary.json), [full case verification](verification.json),
[whole corpus verification](corpus-verification.json), [main paired samples](measurements.json),
[final conservative controls](conservative.json), [alias/stub checks](edge-protocol.json),
[build commands](build-commands.json), and [timed binary hashes](timed-binary-hashes.json).
Raw complete corpus normalizations and disassemblies remain under
`compiler/build/json-twins-20261024/` in the workspace. The two preliminary timing
windows are retained alongside the final results.

The self-contained [sources](sources/) include both parser twins, the shared
helpers, driver, all 1,828 exact inputs, strict independent oracle, fixed-corpus
generator and build/measurement scripts. They need an existing Dyn source build,
GCC, Clang and a Linux x64 C environment; **yyjson is not a dependency**. Nothing
installs or downloads dependencies. A fresh scratch build, corpus generation,
full case verification and alias/stub checks passed using only this archived
bundle and the specified compiler. Copy them to a scratch directory and run:

```sh
export DYN_SOURCE_ROOT=/absolute/path/to/dyn/compiler
work=$(mktemp -d)
cp -R "$DYN_SOURCE_ROOT/docs/performance/2026-10-24-json-twins/sources/." "$work/"
python3 "$work/build.py"
python3 "$work/generate-input.py"
export JSONL_INPUT="$work/events.jsonl"
python3 "$work/verify.py"
python3 "$work/verify-corpus.py"
python3 "$work/edge-protocol.py"
python3 "$work/measure.py"
python3 "$work/conservative.py"
```

The measurement scripts pin CPU 2; adjust that explicitly for a host where CPU 2
is unavailable. Do not overlap measurements with builds or other benchmarks.
Keep this as a parser-core emission result on a documented host, not a universal
ranking of languages or backends.
