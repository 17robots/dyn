# Points and sieve compute gaps

Read-only source investigation. Isolated binary probes only. No timing runs, product changes, compiler rebuild, or commits.

## Equivalent work

Points C and Dyn both initialize 4096 signed 64-bit x/y pairs, then perform 2000 updates with signed remainder modulo 1000003, then sum pairs. Initial y <=28665. Every subsequent x/y lies in [0,1000002], so x+5 and 3*y+11 cannot overflow i64. Total sum also fits i64. Thus C signed-overflow undefined behavior does not alter this input domain. Both outputs: 2094662128. Both already use multiply-high reciprocal remainder, not hardware integer division. Neither hot update loop is vectorized. GCC-O2 vectorizes only the final 4096-element sum, negligible versus 8192000 updates.

Sieve C and Dyn both reset 8000000 bytes ten times, inspect positions 2..7999999, mark multiples starting at 2*i, and aggregate prime counts plus round ordinal. i and j are 64-bit unsigned in both. Mark loop exits below 16000000, so arithmetic never overflows. Output: 5397815. Algorithms and byte storage match. Neither marking loop is vectorized.

## Concrete generated-code differences

Points Dyn main starts 0x20b900. Hot loop stores aggregate argument x/y to [rbp-0x30]/[rbp-0x28], reloads both, and loads identical reciprocal into r11 twice per update. GCC-O2 leaves arguments in registers, hoists reciprocal outside both loops, increments point pointer by16, and uses LEA for 3*y+11. Dyn computes byte offset via shifted ordinal and keeps checked add/multiply branches. Existing check-suppression measurements show those branches do not explain most of the gap; the redundant aggregate stores/reloads are independent of safety checks.

GCC-O3 is not a stronger baseline for this fixture: it interchanges point/round loops and combines two rounds per iteration. Each point then has a long recurrence instead of interleaving independent points across rounds. This is a plausible latency explanation, not a measured causal claim. A GCC -O3 -fno-loop-interchange binary is ready to isolate this decision.

Sieve Dyn main starts0x20b8c0. Dense outer scan loads a byte to a register, compares 64-bit value, and copies count through rdi/rcx across each branch. GCC compares memory byte directly, preserves count register, and uses an incremented2*i induction value. Marking loop itself is nearly identical: store byte, add stride, compare limit, backedge. Dyn fills with REP STOSB; C calls libc memset. Setup/reset cost needs isolated measurement before attribution.

## Frozen causal probes

Run binaries listed in probes.json against unchanged checked binaries. Each changes only named byte sequences; code addresses and all safety checks remain fixed. Every probe passed one full-size exact-output check. No timings ran here.

- points-stack: eliminate aggregate temporary via otherwise free caller-saved r10; remove redundant x roundtrip.
- points-magic: remove second repeated reciprocal reload, using unchanged r11.
- points-stack-magic: combine those changes.
- sieve-cmp: memory-byte comparison instead of zero-extend plus 64-bit comparison.
- sieve-phi: keep count in rcx, removing branch copies.
- sieve-fill: fill same8000000 bytes with REP STOSD, 2000000 iterations and replicated0x01010101. Uses entry DF=0 ABI guarantee.
- sieve-cmp-phi: combine compare and count changes.
- sieve-all: combine compare/count/fill changes.
- points-c-O3-no-interchange: gcc -O3 -fno-loop-interchange compiler/tools/bench/points/main.c -o compiler/build/final-gap-20261025/compute/points-c-O3-no-interchange. Output2094662128; SHA256 ad9e11017963d3bd8665fdd2cbbf2d584847a3c9194d1b3577222ac2da600f49.

Exact binary patches, hashes, and outputs: probes.json. Reproduction: python3 compiler/build/final-gap-20261025/compute/make_probes.py. This script performs correctness executions only.

## Safe improvement candidates

1. Aggregate temporary scalar forwarding for nonescaping, alias-safe snapshots. Points contains a specific redundant stack roundtrip. A compiler implementation must preserve source evaluation order, aliasing, effects, and checked-failure ordering; benchmark-specific register patch is not a general implementation.
2. Register copy coalescing across count PHIs. Sieve has avoidable moves in the dense scan.
3. Fold integer memory load plus comparison when loaded value has no other use; preserve exact width and signedness.
4. Constant-byte fill strategy in ssa_fill_memory (ssa.inc:5446). REP STOSD is a probe; retain only after size-distribution benchmarks and tiny/unaligned/tail tests. Never assume wider stores are aligned-safe on other architectures.
5. Reciprocal constant reuse/hoisting and address induction selection. These are broader allocator/loop improvements, requiring more evidence.

## Limits

Binary probes are narrow attribution tools, not production patches. NOP padding preserves addresses but changes instruction/decode behavior; gains cannot be assigned exclusively to abstract instruction count. Full-size checksum equality is fixture correctness evidence, not exhaustive optimizer validation. No conclusion yet about timing causality, noise, other CPUs, cache states, or different input distributions. No universal C-speed conclusion follows from these two kernels.
