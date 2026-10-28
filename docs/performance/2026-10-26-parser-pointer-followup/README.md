# Cleanup pointer proofs and mutable JSON scanning — 2026-10-26

This follow-up improves the measured map workload by 9.6%, JSONL reporting by
8.2%, and the handwritten UTF-8 workload by 5.1%, using paired process-time
ratios. It preserves safety checks, cleanup behavior, allocation, and zeroing.
The remaining gaps to C are not closed.

## Product changes

1. Cleanup lowers pointer guards to ordinary branches. The proof pass now
   recognizes exact equality/inequality tests against zero for known nonnull
   frame addresses and unoffset compiler-owned globals. It also proves low-bit
   alignment tests when the address facts establish that alignment. Only the
   block control changes; shared comparison values retain their meaning.
2. Mutable JSON now uses the same trusted ASCII-prefix helper as compact JSON.
   On x86 SSA, the existing bounded SSE2 scanner skips ordinary ASCII; other
   paths retain the scalar helper. The full decoder still handles quotes,
   escapes, controls, UTF-8, ownership, and error offsets. Scanner setup requires
   at least 16 remaining bytes and an ordinary ASCII first byte.

Review caught two unsafe proof generalizations before acceptance. Arbitrary
address arithmetic can wrap to zero, so alignment facts alone cannot establish
nonnull. Foreign globals may have byte alignment, so the shared address facts
now exclude foreign storage. Regressions compare a wrapped address without
reading it, and use an independently placed odd-address C symbol.

## Method and final results

The baseline is merged main `3cb6a0da`, before these changes. The baseline and
candidate use identical project and SDK paths, generic CPU, release O3, no cache,
and the same benchmark inputs. C controls are the retained GCC O3 executables;
the application uses `-march=x86-64`. The host is Linux x86-64, pinned to CPU 2.
Runs are serial, with three warmups and 25 recorded samples per variant, in
randomized order. Each output is checked; application JSON is compared as
objects. Binary hashes are checked before and after timing.

The ratio column is the median of paired candidate/baseline samples, with a
bootstrap 95% interval. It need not equal the ratio of the two separate medians.
Milliseconds are whole-process times, not isolated loop-cycle measurements.

| Workload | Baseline ms | Candidate ms | C ms | Paired candidate/baseline [95%] |
|---|---:|---:|---:|---:|
| map | 43.891 | 39.670 | 35.305 | 0.9039 [0.9014, 0.9064] |
| allocate | 27.746 | 27.160 | 23.392 | 0.9786 [0.9765, 0.9807] |
| utf8 | 55.462 | 52.498 | 31.385 | 0.9489 [0.9418, 0.9545] |
| jsonl | 43.725 | 40.143 | 13.457 | 0.9178 [0.9152, 0.9233] |
| search | 9.484 | 9.674 | 32.510 | 1.0023 [0.9759, 1.0337] |

[Raw samples, commands, hashes, outputs, and run order](results.json).
[Final compiler and binary identities](build.json).

The map still takes about 1.12 times the C time, and UTF-8 about 1.67 times.
JSONL takes about 2.98 times the C application time. That application comparison
uses different parser implementations and does not isolate language/codegen
cost. Search has no statistically resolved change in this run. These are
workload results, not a ranking of languages or a claim of universal C parity.

The compiler-only proof change, scalar JSON prefix, and combined implementation
were first built separately. Those initial factorial observations and the
isolated UTF-8 experiment are retained in
[factorial-and-experimental.json](factorial-and-experimental.json). They predate
the JSON scanner setup gate; use the final results above for the shipped source.
After excluding foreign symbols from the proofs, rebuilt map/UTF-8 binaries
were byte-identical to those initially measured. JSON was rebuilt and remeasured
with the final gate.

## JSON string trade-offs

Opaque input arrives through a separately compiled C driver. Every parse owns
its output, resets its arena, and contributes an independently expected
checksum. Both versions use the same driver and exact document bytes.

| String | Parses | Baseline ms | Candidate ms | Paired candidate/baseline [95%] |
|---|---:|---:|---:|---:|
| empty | 500,000 | 9.520 | 9.573 | 1.0062 [0.9987, 1.0153] |
| ascii1 | 500,000 | 12.332 | 12.431 | 1.0057 [0.9927, 1.0146] |
| ascii7 | 500,000 | 14.312 | 14.345 | 0.9980 [0.9883, 1.0106] |
| ascii16 | 500,000 | 17.778 | 14.132 | 0.7915 [0.7851, 0.7999] |
| ascii64 | 500,000 | 41.336 | 19.484 | 0.4762 [0.4585, 0.4817] |
| ascii4096 | 25,000 | 81.948 | 26.186 | 0.3206 [0.3180, 0.3292] |
| escaped64 | 100,000 | 57.005 | 55.231 | 0.9683 [0.9556, 0.9754] |
| utf8-64 | 250,000 | 40.722 | 38.987 | 0.9634 [0.9449, 0.9812] |

[Raw samples](json-strings.json) and [build identities](json-string-build.json). The first ungated scanner slowed empty-string
parsing by about 2.5% and the non-ASCII sample by about 1.7%.
[Those rejected measurements](json-strings-ungated.json) motivated the gate.
With the final gate, the intervals for empty and very short strings include no
change. The long-ASCII gains are specific to these samples; the JSONL application
improves much less because scanning is only part of its work.

The standalone fixture is in `json-string-fixture/`. Compile `driver.c` using
`cc -O2 -ffreestanding -fno-stack-protector -c`, then build the Dyn directory with
`--release --opt-level 3 --cpu generic --no-cache --emit-object --link DRIVER.o`.
Send `CASE ROUNDS` on stdin. Cases 0–7 are empty, ASCII lengths 1/7/16/64/4096,
64 escaped characters, and 64 decoded UTF-8 bytes. Per-parse checksums are
`4,199,205,214,262,4294,262,432` respectively.

## UTF-8 register experiment: not a product change

The decoder is a handwritten nonvalidating benchmark, not `std/unicode/utf8`.
CFG liveness demonstrates that continuous allocation intervals prevent some
safe register sharing. An isolated postallocation coalescer removes two inner
accumulator copies and checksum transfers. In the matched common-driver run,
baseline 52.266 ms becomes 50.858 ms; the paired ratio is 0.9726 with interval
[0.9579, 0.9849]. The C decoder takes 29.700 ms.

Seven thousand independent C comparisons per probe/baseline/tree mode pass,
as do checked-failure comparisons and bounded/OOM decline controls. Static
review found no alias, PHI, clobber, or spill issue. It remains experimental:
compile cost, broader workload performance, and dedicated destructive-alias
regressions are not qualified. This patch does not change register allocation.

## Qualification and remaining work

- Strict debug and release compiler builds pass.
- Twelve cleanup/address cases match tree execution, including exact failures
  and cleanup traces. All four ILP32 configurations pass constructed/live
  preflight. The old compiler fails the emitted-check negative control.
- JSON ASCII helper tests pass for compact/mutable, SSA/tree, all byte values,
  odd starts, protected ends, and live floating values. Lookalikes keep their
  ordinary bodies. Owned-string regressions cover threshold boundaries and
  resumption into escapes, malformed UTF-8, and controls.
- JSON read correctness, native SSA on four targets, bounds, constants, hot
  intervals, flags, subtraction, spills, native optimization, byte provenance,
  and frontend/codegen allocation-failure checks pass.
- Eight JSON-read guests pass across RV32/Thumb, hard/soft, debug/release; soft
  images pass the no-FP instruction audit. This is CPU emulation, not board proof.
- Formatting, std lint, and documentation snippets pass.

Full repository CI remains a separate gate. Physical-board qualification is
unchanged. No release is published by this work. Remaining investigations are
map invariant/check reuse, JSON parser/allocation work beyond ASCII scanning,
and the isolated register experiment. None justifies disabling checks or
changing zero-initialization semantics.
