# Isolating JSON design and generated-code costs

This investigation changes no compiler, runtime, standard library or DNA source.
It tests three hand-matched Dyn/C kernels and isolates DOM parsing under one C
harness. It demonstrates specific implementation costs, not an inherent speed
limit of the language or a universal C-equivalence claim.

## Method

All measurements run serially on CPU 2, on the same Linux x64 host. Code is
compiled at O3 for generic x86-64. The identical C harness reads each input before
timing, loads one shared library, and makes one function-pointer call per kernel.
The three kernels scan the fixed JSONL corpus or traverse a generated array of
one million two-word records. Each binary receives identical bytes and repeat
counts. Two warmups precede nine rotating/reversing samples per variant.
Checksums have independent Python oracles. There are 1,525 additional functional
controls, including all byte values, random inputs, numeric overflow, duplicate
JSON keys and malformed nesting.

C's default unsigned arithmetic wraps. A separate C variant checks accumulator
overflow with `__builtin_add_overflow` and aborts on failure. The integer parser
has the same explicit u64-limit validation in all variants. This matches relevant
arithmetic on successful inputs; it does not give C Dyn's pointer/alignment and
slice safety contracts. Bounds on all valid benchmark accesses follow from their
loops. Invalid-pointer behavior and failure diagnostics are not equivalent.

The Dyn wrapping variant uses explicit `#wrap` only for arithmetic payloads.
It is an experimental control, not a proposed removal of safety from library code.

## Matched kernels

Medians in milliseconds; each row includes the repeat count shown. Times across
rows do not represent equal amounts of work and must not be summed.

| Kernel | Repeats | Dyn checked | Dyn wrapping | GCC ordinary | GCC vectorization disabled | GCC checked arithmetic |
|---|---:|---:|---:|---:|---:|---:|
| Classify quote, backslash and control bytes | 10 | 78.52 | 77.37 | 15.32 | 97.53 | 53.65 |
| Validate and accumulate integer tokens | 5 | 38.03 | 43.82 | 16.18 | 15.96 | 35.15 |
| Sum selected two-word records | 20 | 7.16 | 6.96 | 6.78 | 6.74 | 3.72 |

The byte classifier's GCC ordinary version uses SSE2 vector operations. Dyn's
version is scalar. Disabling GCC vectorization makes this particular C loop
slower than Dyn. That isolates a compiler optimization difference; it does not
show that vectorizing the full parser would yield the same improvement.

For integer scanning, the apparent 2.35x gap against ordinary C becomes about
8% against checked-arithmetic C. This is evidence that safety semantics matter
in this kernel. It is not a precise attribution of all overhead to checks:
adding checks changes optimization and layout, and Dyn's wrapping version is
actually slower here.

Dyn's generated integer loop also contains a slice-bounds check despite the
loop condition already bounding the same index. It materializes the same large
u64-limit constant twice inside the digit path. GCC keeps that constant outside
the loop and uses a tighter digit-range test and address arithmetic. These are
concrete optimizer opportunities. No product patch is made from this probe.

Record traversal is within about 6% of ordinary GCC on this fixture, while GCC's
checked version is unexpectedly faster than both. Inspection confirms it still
reads records in each repeat. This demonstrates sensitivity to generated loop
shape rather than uniform speed parity or a uniform safety penalty.

## Parsing under an identical driver

A second harness path uses C `memchr` for line boundaries, then calls a parser
wrapper once per nonempty line. It includes the final unterminated line. Both
wrappers parse complete DOMs and return their root member counts. Dyn reuses a
1 MiB arena and rewinds between documents; yyjson uses its ordinary allocator
and releases each document. Dyn owns copied input; yyjson uses its normal
non-insitu read API. No schema extraction, aggregation or output serialization
occurs. These are different parser algorithms and APIs, not a translation of
one implementation between languages.

Five passes over 60,000 records, eleven alternating samples after two warmups:

- Dyn compact reader: **145.985 ms**, or 29.197 ms/pass.
- C/yyjson: **23.006 ms**, or 4.601 ms/pass.
- Root-member checksum: **2,700,000**, independently validated.

The approximately 6.35x parsing-region gap remains a mix of parser implementation,
allocation strategy and generated code. Shared-library wrappers and their call
contexts differ from the whole application, so these figures must not be
subtracted directly from earlier executable timings or replace their results.
The original whole-application comparison remains about 39.84 vs 13.30 ms.

An earlier experimental driver scanned lines inside each language. Its results
are preserved as `parse_lines` in the raw kernel data, but those include generated
line-scanning code and are not used as the parser-isolation headline.

## Conclusions and next discriminating experiments

There is no evidence here of an unavoidable language-level speed ceiling.
There is clear evidence of missing or weaker compiler optimizations, and the
library parser still has a large unexplained gap. Neither conclusion excuses
the measured slowdown or establishes that Dyn is universally as fast as C.

The most discriminating next work is to translate one complete parser hot path
between languages with the same state layout, validation and error behavior;
then separately test redundant-check elimination, loop-invariant constants and
vector byte classification. Each candidate needs correctness and end-to-end
application measurements. Kernel wins alone are insufficient.

Raw measurements: [kernels](results.json), [common-driver parsing](driver-results.json),
[functional controls](controls.json), [environment and hashes](environment.json).
Sources are archived under `sources/`. Original executable artifacts,
disassemblies and executable Python drivers remain under
`compiler/build/json-language-isolation-20261024/` in this workspace.
The archived Python scripts retain that local artifact layout; they are evidence
and local rerun drivers, not portable installed test commands. Build commands use
`dyn-release build PROJECT --release --opt-level 3 --cpu generic --shared --no-cache`,
and `gcc -O3 -march=x86-64 -fPIC -shared kernels.c -lyyjson`. The scalar control adds
`-fno-tree-vectorize`. The common C harness is built with `gcc -O2 harness.c -ldl`.

This is finite same-host qualification of investigation fixtures. No repository
suite rerun, other-backend execution or DNA performance claim is part of this pass.
