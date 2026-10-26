# Remaining gaps to C, and five fixes — 2026-10-25

**Allocation now runs at 1.12× C, down from 4.4×.** UTF-8 decoding is now
1.64× C, down from 3.27×. A `sin`-heavy loop is now 1.26× C, down from 1.86×,
and large-argument `sin` is 2.08× C, down from 37×. The second round of fixes
is described under [Follow-up fixes](#follow-up-fixes).

## Method

The host is a Linux x86-64 Ryzen 9 9950X, with every run pinned to CPU 2.
Binaries are built with release and O3 for generic x86-64, and C with
`gcc -O2`. Each timing is a whole process: two warmups, then the median of 21
runs. Before and after use the same source and the same checksums. Hot code
was found with `perf record -e cycles:u`, running in a container image
(`localhost/dyn-perf`); the host has no perf.

## Results

Milliseconds; lower is better.

| Kernel | Before | After | C | After / C |
|---|---:|---:|---:|---:|
| UTF-8 decode (`extended.py utf8`) | 15.816 | 7.934 | 4.836 | 1.64× |
| Hash map (`extended.py map`) | 6.611 | 5.603 | 4.899 | 1.14× |
| Sort (heapsort vs `qsort`) | 16.217 | 16.115 | 17.852 | 0.90× |
| Allocation (`extended.py allocate`) | 14.574 | 14.563 | 3.325 | 4.38× |
| `sin` loop, 5M calls, small arguments | 59.546 | 40.169 | 31.849 | 1.26× |

The `tools/bench/run.py` kernels show no meaningful change: fib 0.40×,
hash 1.00×, matmul 0.88×, points 1.31× and sieve 1.23× C. The raw rows for
the extended kernels are in [extended.json](extended.json).

## What each fix removes

1. **Unsigned shift by a constant.** `c << 6` was checked by shifting back and
   comparing, in 6 instructions. It is now one compare against `2^(bits-k)`.
2. **The index step after a bounds check.** In `i += 1` following `v[i]`,
   `i` is already below the length, so the overflow check cannot fire. The
   check is now removed in both of its forms: the flag form, and the explicit
   compare used when `defer`s are pending.
3. **Cold calls kept hot values out of registers.** With a `defer` pending,
   every check's failure path calls the cleanup. The allocator counted those
   calls as clobbering every caller-saved register. It now ignores a call in a
   failure exit block when the value is not used there. In the UTF-8 kernel,
   `main` drops from 56 spill slots to 17.
4. **Failure blocks were laid out inline.** Every passing check jumped over
   its cold cleanup block. Blocks that can only end in a failure exit now go
   after all other blocks, so passing checks fall through. This is the
   largest single UTF-8 gain: 0.68 → 0.42 ms per decode round.
5. **The inliner skipped calls that were not evaluated first.** It now
   expands a call in the right operand when the left operand is a literal or
   a local no pointer can reach, as in `exponent - high(x)` and
   `w == inf()`. It also expands calls in compound assignments to such locals,
   as in `total += sin(x)`.
   - "No pointer can reach" means the local is never the base of `&`, of a
     slice, or of a pointer `for`.
   - Calls to byte and JSON intrinsics stay calls, so their SIMD lowering is
     kept.

The constant fold of `-constant` for floats (no more `xorps` sign mask) is
also included; its effect is small.

All 715 regression tests pass.

## Follow-up fixes

The first round left five gaps. Four are fixed; the fifth is a safety cost
and stays.

| Kernel | Before | After | C | After / C |
|---|---:|---:|---:|---:|
| Allocation (`extended.py allocate`) | 14.563 | 3.504 | 3.126 | 1.12× |
| `sin`, arguments ≥ 2^20 | 37× C | | | 2.08× |
| `sin` loop, small arguments | 40.169 | 39.3 | 31.8 | 1.24× |

The raw rows for the allocation run are in
[unwind-tables.json](unwind-tables.json).

1. **Table-driven unwinding (allocation).** Direct calls between Dyn
   functions, and `#panic`, no longer register a cleanup frame at run time on
   x86-64 Linux. Each object gets a `dyn_unwind` section that lists:
   - for each function, its code range and where it saves `rbx` and
     `r12`–`r15`, relative to `rbp`;
   - for each protected call, its return address and its landing pad.

   On panic, `dyn_panic` captures its caller's registers. The runtime then
   walks the frame-pointer chain. At each frame it does one of three things:
   - jumps to a handler that was registered in that frame or a deeper one;
   - jumps to the call's landing pad;
   - restores the frame's saved registers and moves to the caller.

   `dyn_unwind_continue` resumes the same walk after cleanup. Foreign and
   indirect calls still register a handler, because C frames without tables
   may sit between them and the panic. At a frame with no table, the nearest
   registered handler takes over.

   About the section:
   - It uses `SHF_LINK_ORDER`, so `ld.lld` keeps it exactly when its code is
     kept.
   - The built-in linker does the same, and defines `__start_dyn_unwind` and
     `__stop_dyn_unwind`.
   - Shared libraries walk their own tables.

   `DYN_NO_UNWIND_TABLES=1` restores registration everywhere; the new
   `tests/unwind-tables.py` checks that both paths produce the same output.
2. **Large-argument trigonometry.** `reduce_pi2_large` now multiplies only a
   window of 2/π limbs around the argument's exponent, as musl does. The
   medium path starts at musl's threshold. Results stay within 1 ulp on 655
   test arguments.
3. **Float comparisons.** On x86-64, `<`, `<=`, `>` and `>=` used by a branch
   are now one `ucomis` and one `ja` or `jae`. The operands are swapped for
   `<` and `<=`, so NaN needs no parity test. Equality keeps the
   materialized form.
4. **Block order.** When a branch leaves a loop, the loop body is now laid
   out before the exit. This removes a jump per sieve iteration, about 2%.
   Live intervals still have no holes; no kernel measured here needs them.
5. **UTF-8 inner loop, not changed.** The remaining bounds and shift checks
   guard against malformed input. Removing them would need range analysis
   on loop-carried values. C has no such checks.

All 716 regression tests pass, including the new unwind test.

The JSONL application gap (4.5× C) is covered by the earlier
[C-levels report](../2026-10-24-c-levels/README.md); it was not re-measured
here. The application harness currently fails its Node HTTP check, which is
unrelated to Dyn.
