# UTF-8 decoder investigation

This investigation changes no product source and runs no performance measurements. All probes are frozen for serial measurement by the parent task.

## Evidence

The existing whole-process UTF-8 workload uses the same scalar algorithm in C and Dyn. Its generated valid Unicode distribution is mostly four-byte sequences. It does not validate malformed UTF-8. Existing measurements include input generation, allocation, and process startup; they do not isolate decoding.

GCC 16.2.1 transforms the C continuation loop into separate straight-line one-, two-, and three-continuation paths. In the original C executable, `main` at `0x17d8..0x1816` handles a four-byte sequence without a continuation-loop counter or backedge.

The check-suppression Dyn executable preserves that continuation loop at `0x20d770..0x20d79d`. Its repeated body has 11 instructions: copy accumulator, shift, byte load, mask, zero extension, OR, index LEA, counter increment, index copy, accumulator copy, compare, then backedge (12 including branch). GCC's non-peeled control has 8 repeated instructions including its branch, using a pointer end test and destructive accumulator update. These counts describe the static body; they are not performance attribution.

The checked isolated decoder adds a shift-overflow check and slice-index check per continuation: at `0x1425..0x143c` in `checked-loop`. Its leading-byte access is already bounded by the outer loop. This explains which additional safety instructions execute; existing suppression timings quantify their aggregate effect, not the complete remaining gap.

No decoder body in these isolated probes spills live state to stack. Stack stores/loads are entry/exit saves of callee-saved registers. The original no-check whole-program decoder likewise has no hot-loop spills. Therefore register spills are not the supported explanation for this particular gap. Register copies and loop state remain concrete code-generation overhead.

## Frozen probes

Every executable accepts `N ROUNDS SEED`. Each uses the exact same C driver to generate valid Unicode, then calls one external decoder over the same buffer. The C driver's integer generator, encoding, checksum output, and allocation are identical across binaries. The decoder's u32 accumulator, usize cursor/count, and wrapping u64 checksum are matched.

- `checked-loop`: original Dyn loop.
- `nocheck-loop`: same source compiled by existing diagnostic check-suppression compiler; unsupported diagnostic only.
- `checked-unroll`, `nocheck-unroll`: explicit branch-local continuation copies, same byte order and scalar recurrence.
- `checked-guardunroll`, `nocheck-guardunroll`: three conditional continuation operations after original count classification.
- `checked-offsetunroll`, `nocheck-offsetunroll`: direct independent shifts and fixed offsets, one cursor advance per sequence. This changes expression shape while preserving valid-input results.
- `c`: original C loop, GCC automatically fully peels its continuation loop.
- `c-no-unroll`: exact same C source and O3 flags except `-fdisable-tree-cunrolli -fdisable-tree-cunroll`. Assembly confirms the continuation loop remains. This is a causal compiler-pass probe, not a proposed C build recommendation.

`prepare.py` builds the probes without rebuilding either compiler. `commands.json` records exact commands. `verify.py` runs four small input combinations for each binary. All 40 executions produce identical checksums, including empty input. `correctness.json` records outputs. Each binary has a `dyn_decode` disassembly in its `.asm` file. `freeze.json` hashes all artifacts at freeze time.

Suggested serial timings: N=262144, ROUNDS=128, SEED=912345. Start with `checked-loop`, `nocheck-loop`, `checked-unroll`, `nocheck-unroll`, `c`, `c-no-unroll`. Measure paired randomized order and verify every output. These results will separate continuation-loop transformation from checks and shared input-generation cost.

## Ranked causes and follow-ups

1. **Bounded continuation-loop peeling:** strongest structural difference. The frozen C pass-disable and Dyn source-unroll probes test causality directly. No speedup is claimed before measurement.
2. **Accumulator/index/counter copies:** concrete overhead even after suppression. Dyn uses a 64-bit SSA integer model and repeated phi transfers; C uses u32 destructive operations and a pointer end condition. Existing code is correct. Source offset-unroll probes expose remaining address/normalization quality.
3. **Redundant unsigned normalization:** `#cast(u32,v[i]&63)` emits a 32-bit self move after a known-small AND. `ssa.inc:2957` extension simplification handles nested extensions, comparisons, and loads, but not a fitting constant AND mask. A narrowly safe fix could remove an extension when the AND mask proves all retained bits already fit. This is a small instruction improvement, not proof of the whole gap.
4. **Bounds/overflow proof:** checked continuation operations retain bounds and shift checks because continuation-count/value correlation is not proved. General branch-sensitive loop unrolling could expose those proofs but requires separate safety and growth validation. The source-unroll probes preserve production checks.

No general UTF-8 library conclusion follows: this is a scalar nonvalidating benchmark, mostly four-byte input. No product fix, timing result, cross-backend proof, or malformed-input claim is supplied by this investigation.

## Parent-authorized masked-extension fix

A nine-line optimization in `ssa.inc` now removes an EXT over AND when either operand is a constant mask fitting the result's unsigned width, or its positive signed width. Width is checked in [1,64]; the unsigned-width-64 case short-circuits before any shift by 64. Signed width 1 safely uses a zero-bit mask. The proof does not infer a bound from variable masks or arbitrary arithmetic.

New `compiler/tests/ssa-masked-extension.py` checks 24 width/sign/order/mask cases over 10016 values each in host SSA and forced tree. Positive instruction bodies must exactly match equivalent no-cast reference functions. Negative bodies must differ and runtime output must equal independent C casts. The baseline fails the first positive control due to its extra MOVZX. The fixed isolated compiler passes. Full-width coverage compiles without undefined shifts. Production source changes remain limited to `ssa.inc`; test registration is left to the parent.

`dyn-masked-extension` is built by replacing only compiler.o in the saved release link command. `fixed-loop` recompiles the original checked isolated decoder; `fixed-extended` recompiles the unchanged full benchmark source. Both pass small checksum comparisons against C. Their compiler, object, binaries, source patch, and test logs are frozen here. No performance measurements have run. Cross-target constructed/live execution and broad suite qualification remain parent work.

Round-two test extension: 52 runtime cases, 520832 comparisons per SSA/tree mode. Added full signed/unsigned64 source wrappers in both operand orders, called and compared against identity bodies (allowing separately unremoved constant-left AND-all-ones). Added negative-bit-pattern masks UINT64_MAX and UINT64_MAX-1 for all 8/16/32 widths and signs. These controls verify retained unsafe narrowing. Source-level full-width normalization may be omitted before SO_EXT, so these tests do not claim SO_EXT64 branch coverage. Focused round-two test passes with the unchanged isolated compiler.
