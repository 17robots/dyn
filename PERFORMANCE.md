# Performance qualification


## Branchless sort, SSA passes, guarded check hoisting and spill coloring — 2026-11-26

`tools/bench/extended.py` (11 interleaved samples, 2 warmups, ms) on x86-64 Linux
against GCC 16.2 `-O2`, Rust 1.94 (`-O`), and Go 1.27:

| kernel | dyn before | dyn after | c -O2 | rust | go |
| --- | ---: | ---: | ---: | ---: | ---: |
| sort (32k × 8 u32) | 11.06 | 2.86–3.04 | 17.76 | 2.27 | 11.86 |
| utf8 (262k × 16) | 6.98 | 4.71–4.96 | 4.83–5.04 | 6.08 | 9.16 |
| map (64k × 8) | 5.93 | 4.72–4.87 | 4.75–4.87 | 4.69 | 5.05 |
| allocate (8k × 32) | 1.26 | 1.26 | 3.11 | 5.43 | 4.97 |

`tools/bench/run.py --samples 7` on x86-64 Linux against GCC 16.2 `-O2`,
Clang 23.1 `-O2`, Go 1.27, and Zig 0.17 (ReleaseFast / ReleaseSafe), seconds:

| kernel | dyn | gcc -O2 | clang -O2 | go | zig | zig safe |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| bodies | 0.016 | 0.016 | 0.016 | 0.049 | 0.025 | 0.025 |
| fib | 0.081 | 0.065 | 0.160 | 0.285 | 0.160 | 0.272 |
| hash | 0.076 | 0.078 | 0.076 | 0.078 | 0.077 | 0.077 |
| matmul | 0.052 | 0.058 | 0.118 | 0.109 | 0.132 | 0.131 |
| points | 0.010 | 0.009 | 0.012 | 0.013 | 0.010 | 0.009 |
| sieve | 0.123 | 0.114 | 0.113 | 0.132 | 0.106 | 0.109 |

`std/sort` now uses pattern-defeating branchless cyclic Lomuto partitioning
(`pdqsort` with Tukey's ninther pivot selection), optimal branchless sorting
networks (`sort2`–`sort8`), and a branchless split-loop bidirectional merge
for slices of 9–16 elements. Extended `sort` drops from 11.06 ms to 2.86–3.04 ms
(3.6–3.9× faster, 3.9× faster than Go `slices.Sort`, 5.8× faster than `qsort`).
`std/unicode/utf8.codepoint_count` also now uses an 8-byte SWAR ASCII fast-path
matching `utf8.valid`.

Eight general SSA backend passes and memory refinements landed in
`src/backend/ssa.inc` and `src/backend/ssa_a64.inc`:

- **Constant-phi jump threading and empty-join flattening**
  (`ssa_thread_const_phis`): flattens chained empty phi-only join blocks from
  nested `if / else if` chains, threads constant-set phi comparisons, and
  specializes small blocks so `utf8` decodes 1–4 byte sequences with zero
  re-tests of the continuation count.
- **Interprocedural slice return-length summary**
  (`ssa_callee_slice_len_param` in `ssa_call`): for any direct slice-returning
  callee whose every return path yields length equal to an unmodified `usize`
  parameter (such as `mem.push_array` or `mem.push_bytes`), callers reuse the
  length argument directly, freeing registers and exposing exact slice lengths
  to `ssa_prove` and loop lowering.
- **Bitmask check rewriting and SSA zero-loop lowering**
  (`ssa_masked_by_cap_m1`, `ssa_zero_loops`, header invariant check hoisting):
  rewrites `(x & (cap - 1)) <u cap` to the exact loop-invariant equivalence
  `cap != 0`, hoists invariant checks from loop headers into preheaders, and
  lowers bounds-check-free `0..N` slice zeroing loops to hardware `REP STOSB`
  (`SO_FILLMEM`), dropping `map` from 5.93 ms to 4.78 ms (faster than GCC
  `-O2` at 4.81 ms and Go at 5.20 ms) and `codegen-bench/map-large` from
  0.740 s to 0.702 s.
- **Chained `SO_ADD` folding, x86-64 index displacement folding, and inductive
  `<=` phi bounds** (`ssa_fold`, `ssa_addressing`, `ssa_phi_bounded_le`,
  `ssa_below_via_phi_le`): folds `(i + 1) + 1` chains after phi threading,
  folds `[base + (idx +/- c)*scale]` into `disp(base, idx, scale)` when the
  offset has no non-address uses, and proves `used <= v.len` across nested
  `if / else if` setup loops so `utf8` drops the per-byte `v[i]` check while
  still coalescing `v[i+1..i+3]` into one check with parallel displacement
  loads — cutting `utf8` from 6.98 ms to 4.82 ms (faster than GCC `-O2` at
  4.89 ms, Rust at 6.37 ms, and Go at 9.51 ms).
- **Pure-read bounds-check coalescing** (`ssa_coalesce_checks`): collapses
  consecutive same-origin index checks on `root + 0..k` inside one pure-read
  block into a single overflow-free check `k <u (len - root)` once `root <= len`
  is established.
- **Inductive phi bound proving and step-above bounds elimination**
  (`ssa_phi_bounded`, `ssa_established_step_above` in `ssa_prove`): proves a
  loop-carried phi stays `<u bound` when every non-self arm is established
  `<u bound` (base range, bound fact, or earlier check), eliminating redundant
  in-loop and post-loop `values[left]` bounds checks in cyclic Lomuto.
- **32-bit unsigned `div`/`rem` narrowing** (`ssa_narrow32`, `SO_DIV`/`SO_REM`
  in x86-64 and AArch64): uses 32-bit `div r32` / `udiv w` when both operands
  fit in 32 bits, avoiding 64-bit divider latency.
- **Guarded preheader hoisting for loop-invariant `SO_CHECK`s**
  (`hoist_checks` in `ssa_hoist`): runs after pure-value hoisting, follows
  single-predecessor `SB_PLAIN` blocks from inlined calls, and hoists
  loop-invariant checks (such as non-zero divisor checks before `%`) into a
  trip-guarded preheader block so 0-trip loops never panic and `>= 1`-trip loops
  check once. Together with 32-bit `div`, extended `map` drops to 5.27 ms
  (beating Go's 5.29 ms, within 1.07× of C `-O2` and 1.09× of Rust).
- **Multi-select flag fusion** (`ssa_fuse`, `SO_SELECT`): fuses a `SO_CMP`
  shared by multiple `SO_SELECT`s in the same block and reuses live
  RFLAGS/NZCV across adjacent selects (`cmp; cmov; mov; cmov` on x86-64,
  `cmp; csel; csel` on AArch64).
- **IEEE-754 exact `2.0 * x -> x + x` folding, inductive sibling-phi bounds
  proving, plain-block coalescing, and x86-64 memory-operand `cmp` fusion**
  (`ssa_fold`, `ssa_phi_step_le_sibling`, `ssa_merge_plain`, `ssa_fuse`,
  `SO_SELECT`, `ssa_compare_values`): rewrites exact `2.0 * x` (`f32`/`f64`) to
  `x + x` (`mandelbrot` 0.233 s → 0.225 s), proves `p1 + d <u bound` from a
  sibling step-1 loop phi `p2 <u bound` (eliminating `values[left + 1]` checks
  in cyclic Lomuto), coalesces single-predecessor `SB_PLAIN` chains after
  `ssa_selects` (collapsing trivial 1-arm phis after `ssa_order`) so `SO_CMP`
  fuses into consecutive `SO_SELECT`s (`cmp; cmov; cmov; cmov`), relaxes
  `SO_SELECT` fusion when `base` is already in destination `d`, and folds
  single-use 64-bit / `u32` loads directly into branch `cmp reg/imm, mem`.
- **Dead-hole register sharing, left-edge spill-slot coloring, and pure leaf
  frame-pointer omission** (`hole_share`, `spill_reuse`, `omit_fp`): generalizes
  dead-hole register reuse before spilling, colors non-overlapping spilled
  values and per-call save slots onto shared stack slots (`tools/codegen-bench.py`
  spills: `argon2` 110 → 77, `json` 68 → 54, `deflate` 74 → 66, `pbkdf2`
  50 → 46), omits frame-pointer prologue/epilogue on zero-frame pure leaves, and
  tightens `SSA_POOL_LIMIT` (4 MiB/worker) and `SsaPipeline.window`
  (`4 * workers`).

`tools/compare/compare.py --sizes 10000 100000 --runs 5`: 100k-line release
build completes in **0.30 s at 80.5 MiB RSS** — #1 fastest and #1 lowest
memory across all four languages (Go 0.32 s / 93.1 MiB, C 0.35 s / 117.1 MiB,
Odin 7.19 s / 619.6 MiB; 10k-line check is 0.01 s / 12.7 MiB). Static zero-libc
runtime binaries drop from 40–48 KiB down to **10–18 KiB** (`fib` and
`mandelbrot` at **10 KiB** — 37% smaller than dynamically-linked C at 16 KiB —
with 0.5–0.6 MiB RSS vs C's 1.6 MiB and full symbol tables intact):

| benchmark | dyn | c -O2 | go | odin | dyn RSS | dyn binary |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| fib | 0.031 s | 0.059 s | 0.108 s | 0.058 s | 0.5 MiB | 10 KiB |
| hashmap | 0.118 s | 0.127 s | 0.135 s | 0.141 s | 129.9 MiB | 16 KiB |
| mandelbrot | 0.225 s | 0.450 s | 0.222 s | 0.224 s | 0.6 MiB | 10 KiB |
| sieve | 0.274 s | 0.272 s | 0.277 s | 0.276 s | 96.0 MiB | 16 KiB |
| sort | 0.614 s | 0.573 s | 0.590 s | 0.571 s | 78.0 MiB | 17 KiB |
| trees | 0.156 s | 0.817 s | 0.508 s | 1.203 s | 10.0 MiB | 18 KiB |

Binary-size and compiler-memory reductions (zero loss of diagnostics or runtime
safety):

- **Release panic fast-path without dead trace tables**
  (`runtime/linux_x86_64_start.S`, `runtime/linux_aarch64_start.S`,
  `runtime/linux_riscv64_start.S`): release builds never dump a stack trace on
  panic, so `dyn_panic` calls `dyn_unwind_begin` directly (preserving
  `panic.set_handler` and stderr reporting) instead of pulling `dyn_trace_capture`,
  `trace_walk`, and `unwind_slot` into every release binary.
- **Stack-buffered scalar formatting in `std/io/io.dyn`**: `print_value` formats
  scalar integers and floats into a 64-byte stack buffer via `fmt.buffer`,
  dropping the `std/mem` arena dependency from programs that only print scalars.
- **Whole-program `case any` arm reachability pruning**
  (`src/ir_reachability.inc`, `src/backend/reachability.inc`,
  `src/backend/driver.c`, `src/backend/ssa.inc`): tracks every type converted
  to `any` (including variadic `...any` arguments) across executable builds,
  falling back conservatively to all arms whenever `any` is dereferenced, cast
  to/from pointer or raw memory (such as `std/reflect`), or crosses a foreign
  boundary; dead `case any` arms (and transitively unreachable formatting/float
  or reflection helpers) are omitted from IR reachability and codegen.
- **Per-function `.text` section splitting for runtime support objects**
  (`src/backend/driver.c`): emits each function in `dynrt_support.o` /
  `dynrt_aarch64_support.o` into its own `.text` section with matching
  `.rela.text` relocations so `src/link_elf.c` automatically garbage-collects
  unused runtime helpers (`race_access`, `fmod`/`fmodf`, `trace_*`, fault
  handlers, etc.).
- **Compact AST/IR records and early source release**
  (`src/dyn_ast.h`, `src/ir.h`, `src/ir.c`, `src/check.c`, `src/codegen.c`,
  `src/main.c`): packs `DynAstExpr` (80 → 48 B), `DynIrExpr` (64 → 48 B), and
  `DynAstStmt` bitfields, frees unmerged `DynSources` immediately after
  `dyn_sources_merge` on `check` and `--no-cache` builds, and trims glibc heap
  after freeing the AST — cutting 100k-line release compiler RSS from 98.7 MiB
  to 80.5 MiB (`check`: 86.0 → 76.3 MiB, `debug`: 98.0 → 79.3 MiB).

`tests/compile-budget.py` and the full test suite (`just test`,
`just test-backend`, `just test-native-debug`, `just test-native-a64`) pass
cleanly.


## Loop elements, hoisting and short loops — 2026-11-26

`tools/bench/run.py`, median of 7 runs on x86-64 Linux, against `cc -O2`
(gcc 16.2), Go 1.27 and Zig 0.17. Times in seconds.

| kernel | dyn | c -O2 | go | zig | /c | /go | /zig |
| --- | --- | --- | --- | --- | --- | --- | --- |
| bodies | 0.015 | 0.016 | 0.048 | 0.025 | 0.96 | 0.32 | 0.61 |
| fib | 0.084 | 0.064 | 0.292 | 0.162 | 1.30 | 0.29 | 0.51 |
| hash | 0.076 | 0.076 | 0.076 | 0.075 | 1.00 | 1.01 | 1.01 |
| matmul | 0.052 | 0.059 | 0.108 | 0.129 | 0.87 | 0.48 | 0.40 |
| points | 0.011 | 0.009 | 0.013 | 0.011 | 1.18 | 0.82 | 1.03 |
| sieve | 0.125 | 0.114 | 0.131 | 0.107 | 1.09 | 0.96 | 1.17 |

`bodies` went from 1.86× C to 0.96×. `for b in bodies` copied each
64-byte element into `b` before the body ran; when the body writes no
memory and never takes `&b`, `b` now reads the element where it lies.
Loop-invariant hoisting also no longer stops at a small integer constant
operand (the constants stay in the loop as immediates), so the expanded
`1.0 + (round % 3)` leaves the inner loop. points and sieve compile to the
same bytes as before; their ratios move with the machine.

A range loop `for j in 0..n`, where n is one of a few constants of at most
four, such as a UTF-8 decoder's continuation count, runs as guarded
straight-line copies of its body. The extended UTF-8 decoder
(`tools/bench/extended.py`) runs about 10% faster: 100 ms against C's 70 ms
on 200,000 characters × 400 rounds, where Rust takes longer than Dyn. What
remains is the bounds check on each byte and re-testing the constant count.

The inliner now lets a pointer parameter given `&local` use the local
directly, so `next(&x)` keeps a generator's state in a register.

`tools/compare` programs, fastest of 5: fib 0.032 s (C 0.060), hashmap
0.132 (0.128), mandelbrot 0.234 (0.449), sieve 0.277 (0.284), sort 0.607
(0.587), trees 0.157 (0.832).


## Against C, Go and Zig — 2026-11-17

`tools/bench/run.py` builds each kernel in Dyn (`--release`), C (`cc -O2`,
gcc 16.2), Go 1.27 and Zig 0.17 (ReleaseFast, and ReleaseSafe, which keeps
bounds checks as Dyn's release builds do), checks the outputs agree, and
reports the median of 5 runs on x86-64 Linux. Times in seconds; the ratio
columns are Dyn's time over the other build's.

| kernel | dyn | c -O2 | go | zig | zig safe | /c | /go | /zig | /zig safe |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| bodies | 0.030 | 0.016 | 0.049 | 0.025 | 0.025 | 1.84 | 0.61 | 1.19 | 1.17 |
| fib | 0.081 | 0.065 | 0.295 | 0.160 | 0.262 | 1.25 | 0.28 | 0.51 | 0.31 |
| hash | 0.076 | 0.075 | 0.075 | 0.075 | 0.076 | 1.02 | 1.01 | 1.01 | 1.01 |
| matmul | 0.051 | 0.056 | 0.106 | 0.129 | 0.128 | 0.90 | 0.48 | 0.39 | 0.40 |
| points | 0.010 | 0.009 | 0.013 | 0.010 | 0.009 | 1.11 | 0.77 | 1.00 | 1.09 |
| sieve | 0.130 | 0.111 | 0.136 | 0.104 | 0.107 | 1.18 | 0.96 | 1.25 | 1.22 |

`bodies` passes a 64-byte struct by value. Before this change it took
0.046 s: an inlined call copied the argument into a parameter, and an
out-of-line call copied it three times (a snapshot, the outgoing stack area
and the callee's frame). Now an inlined body reads a caller's local in place
when it never writes or takes the address of the parameter; a callee keeps a
stack-passed struct where it arrived, or reads a by-pointer one (AArch64,
Windows) through the pointer, outside debug builds; and a caller passes a
local whose address is never taken without a snapshot. An out-of-line call
of a 64-byte struct went from 3.0 to 1.7 ns. What remains in `bodies` is the
copy into the `for b in bodies` loop variable, which C and Zig avoid.

## Editor rewrite reuse — 2026-10-29

`dyn lsp` rewrote the imports of every project file on each edit. A file's
rewrite depends only on its text and on its module's directory, root flag,
declared names and import aliases with their targets; each module hashes
those into a key. The editor's syntax cache now keeps each file's rewritten
text, source spans and patched tree, and reuses them while the text and key
match. Batch builds have no syntax cache and are unaffected.

DNA edit-to-diagnostics latency falls from a median of 53 ms to 11 ms. A
scripted session of seven overlay edits, covering an unknown name, a new
public declaration in another module, its use, its rename and both reverts,
publishes identical diagnostics before and after.

## Allocations, editor latency and debug builds — 2026-10-29

A DNA release build made 720,000 heap allocations; it now makes 212,000.
Name lookups during import rewriting and reference checks copy names into
inline buffers instead of the heap. SSA block, predecessor and call argument
lists come from a per-function arena released at once. Passes take one block
for all their scratch arrays. IR keeps every declaration and local name in
one pool. Rewrite replacement texts come from a per-file arena. Short AST
blocks collect statement ids on the stack.

Editor analysis in `dyn lsp`, measured as the time from a one-character edit
of DNA's main.dyn to its diagnostics, falls from a median of 192 ms to 53 ms:

- The syntax cache held 64 entries and 8 MiB, fewer than one project's
  sources, so least-recently-used eviction missed on every file of every
  edit. It now holds 4096 entries and 128 MiB.
- Rewritten imports patch their trees under a work budget too, charging about
  what parsing would cost.
- Line and column lookup counts newlines with `memchr`, and source maps and
  edit spans are binary searched.

Interleaved medians for DNA:

| | Before | After |
|---|---|---|
| Release build | 140.5 ms, 126 MiB | 112.4 ms, 129 MiB |
| Debug build | 118.5 ms, 105 MiB | 91.6 ms, 101 MiB |
| `dyn check` | 67.0 ms, 59 MiB | 50.1 ms, 66 MiB |
| Editor edit | 192 ms | 53 ms |

Objects stay byte-identical on 46 project and target builds. The debug
build's tree emitter, about 31 ms, remains serial.

## Parallel frontend — 2026-10-29

Function bodies lower to the AST on up to four worker threads. Each worker
lowers a run of bodies into private arrays; the runs merge in function order,
shifting their ids and interning new types in creation order, which assigns
exactly the serial ids. A run that reports a diagnostic sends the whole
program back to serial lowering, so messages keep their order. Structure
checks of declarations and bodies also run on workers, and each body is
walked once instead of twice.

Serial work also shrank: type predicates are inline, import rewriting
resolves each file's directory once instead of four times, and IR lowering
builds the source location index once and resolves each SDK path once. The
backend's default worker cap rises from four to six; its smaller window keeps
the memory cost to about 4 MiB.

DNA, interleaved medians: 140 → 117 ms wall, 334 → 345 ms CPU,
127 → 132 MiB peak RSS. Stages: import loading 27 → 20.5 ms, AST lowering
23 → 14.5 ms, type checking 17.4 → 14.7 ms, IR lowering 10.8 → 8.7 ms.
Objects stay byte-identical on 46 project and target builds.

Runs merge in order as soon as each finishes, so only runs still in flight
exist beside the program; a run that reports a diagnostic truncates the
program back to its earlier counts before the serial retry. Worker heap
arenas would otherwise hold the merged runs' memory for the rest of the
build, so glibc builds return it with `malloc_trim` after the merge.

Import loading falls from 20.5 to about 17 ms. Imported directories load
from a work queue as soon as an import names them, instead of level by level
with a barrier after each level. Sources copied out of the prefetched
directories keep their snapshot's facts instead of walking every node again.

`dyn check` on DNA falls from 66 to 50 ms; its peak RSS, set during AST
lowering, rises from 60 to 64 MiB. Linking DNA takes 2.4–5 ms of a full
release build, so the linker is not a bottleneck.
A parallel inliner was measured and dropped: rebuilding bodies is memory
copying, and the merge copied it again for no gain and 10 MiB more peak RSS.
Type checking stays serial because instantiating generics creates functions
whose ids later checks depend on.

## Compiler throughput and memory — 2026-10-29

The native backend now prepares functions on up to four worker threads, at
most 16 functions per worker ahead of in-order emission on the calling thread.
`DYN_BACKEND_JOBS` overrides the worker count. String literals prepared on
workers are interned in encounter order at emission, so objects stay
byte-identical to serial builds.

Algorithmic changes cut single-threaded work as well:

- The range prover indexes branch facts by value and tests dominance in O(1)
  with dominator-tree DFS intervals; CSE uses the same test.
- Liveness groups cross-block uses by value, so no block is walked twice for
  one value.
- Optimization rounds stop after five passes in a row change nothing, and
  operand resolution runs only after a pass that changed something.
- Range queries are memoized within each prove pass.
- Load forwarding skips its second region classification when nothing was
  forwarded, and forwards runs of disjoint same-base stores across
  straight-line blocks.
- Import rewriting patches the parsed tree instead of reparsing each file:
  renames shift offsets and `alias.member` collapses into one name. Edits of
  any other shape still reparse.
- The inliner appends to the expression and statement arrays in place instead
  of copying them first.
- The parser handles literal tokens before testing keyword spellings, which
  halves the load time of generated data tables.
- Struct layout is memoized per object.

Byte fills of global byte arrays now apply at O2 as well as O3 (x86 only).
They are the only intended code change; all other changes keep objects
byte-identical on 46 project and target builds.

Interleaved medians, x86_64 Linux, release object builds without caches,
measured with `tools/bench/compile.py`:

| Project | Before | After | CPU before / after | Peak RSS before / after |
|---|---|---|---|---|
| DNA (62k lines) | 461 ms | 141 ms | 550 / 339 ms | 154 / 127 MiB |
| http-server | 25.3 ms | 13.6 ms | | 36 / 42 MiB |
| std fixture | 27.4 ms | 16.7 ms | | 26 / 34 MiB |

DNA single-threaded (`DYN_BACKEND_JOBS=1`) falls from 348 to about 230 ms.
Sieve runtime falls from about 1.23x to 1.17x of `cc -O2`. Small projects use
a few MiB more peak RSS because the worker threads and their stacks dominate.

The remaining serial cost is the frontend: AST lowering, type checking and IR
lowering take about 55 ms of DNA's build before the backend can start.

## Real-application follow-up — 2026-10-20

The real-project matrix covers a 10.8 MB JSON validation input, a PTY-driven
Field Notes session, DNA's existing document-buffer workload, and its complete
headless search/open/edit/undo workflow. JSON and Field Notes require isolated
API-adapted copies because the checked-in examples use retired memory APIs.
DNA sources and its buffer workload remain unchanged. Both compilers use the
same staged sources, input bytes, SDK and native libraries.

Five paired cold-build samples measure JSON at 160,384 / 42,688 bytes and about
30.7 / 10.8 ms before/after all changes. Field Notes measures 81,112 / 35,664
bytes and about 9.7 / 7.6 ms. DNA's buffer remains 149,384 bytes; the editor falls
only from 1,564,040 to 1,559,944 bytes, with build time roughly unchanged near
0.31 s. External inputs conservatively preserve public roots, limiting pruning
benefits in these two applications.

Runtime profiling finds PCRE2 as the editor's largest sampled leaf. Its replay
also contains scheduled waits, so its approximately 43 s wall duration is not
an interactive-latency measure. The 30-run GDB/MI JSON profile records string
scanning in 99 of 131 PC samples. These are directional samples, not hardware
cycle counts. Disassembly exposes repeated loads of unchanged cursor fields.

A new SSA pass reuses identical typed loads only within one basic block.
Memory writes, calls and copies invalidate reuse; no pointer non-aliasing or
cross-block assumptions are added. Fifteen shuffled runtime samples recover
the intermediate compiler's JSON regression: about 14.9 / 12.8 ms immediately
before/after load reuse. The original compiler also measures about 12.9 ms,
so the cumulative result retains smaller code while restoring original speed.
The standalone cursor and DNA buffer benchmarks show little runtime change.
This is not a general runtime speedup claim.

Separate native-launcher measurements avoid Python's inherited RSS floor.
JSON remains about 10.3 MiB peak RSS; Field Notes about 0.5 MiB; the buffer
workload varies around 4–5 MiB. No meaningful allocation reduction is shown.
The editor's final integration run records 50.6 MiB peak RSS; its single final
sample does not establish a memory improvement over the earlier paired runs.

The complete compiler suite and the focused load-reuse gate pass. The new
code-generation assertion fails on the preceding compiler, which emits two
reads of the same pointer instead of one. Tests preserve aliasing stores,
partial writes, calls, overlap copies, zeroing, branches and loop-carried writes.
The rebuilt editor passes its workflow probe and matches full-reference Unicode,
tab and zoom rendering pixel-for-pixel. Raw data and scripts are retained under
`build/real-app-performance/`; the cursor benchmark lives in
`tests/performance/cursor`, and the gate is `tests/native-load-reuse.py`.

## Independent backend update — 2026-10-20

Native release executables now compute function reachability before scalar
optimization and inlining. Unused public bodies are skipped when the compiler
has the complete executable and no external link inputs. Explicit object or
assembly output, libraries, debug output, and Wasm retain their public-root
policies. Global initialization, callback addresses, and cleanup remain live.
Object cache keys distinguish builds with external public roots, so adding an
external object cannot restore an executable object with required symbols pruned.

O3 uses cached expression-aware callee costs and a program expansion budget.
ELF x86-64 code sections now declare the 16-byte alignment required by SSA loop
padding. Detailed timings separate reachability, scalar optimization, inlining,
SSA construction/optimization, register allocation, machine emission, and object
serialization. Backend totals aggregate per-function work and sit inside the
overall native emission time; they are not additional command wall time.

Seven shuffled samples after warm-up on this Linux x86-64 host measured the
standard-library fixture as follows. Portable O2 executable size falls from
143,592 to 36,928 bytes; cold build median falls from 29.30 to 10.04 ms. O3 size
falls from 310,560 to 37,240 bytes; build median falls from 112.91 to 10.56 ms.
The five smaller kernels produce O2 files about 32% smaller, with build times
about 9–17% lower. Compiler caches are disabled; OS caches remain warm.

Runtime is workload-dependent: O2 Fibonacci is about 2.6% slower, O3 matrix
about 8.1% faster, and O2 sieve about 4.8% faster. Other changes are small.
Every output/checksum matches. These samples establish size/build improvements,
not a universal runtime improvement. The comparison uses a preserved pre-change
compiler binary, not a fresh rebuild of old sources.

The complete standalone regression suite passes after the final alignment fix.
New tests check seven-target executable pruning, retained exports and external
callbacks, initializer/defer effects, cache reuse, ELF code alignment, and bounded
inlining. The growth regression fails with the old compiler: its O3 object grows
from 3,832 to 18,240 bytes. The new compiler passes the growth limit.

Raw commands, samples, compiler/artifact hashes, and logs are retained locally
under `build/performance-implementation/`. Final paired samples after the cache fix are in
`final-measurements/results.json`; `compare-aligned.py` reproduces them when the
preserved baseline is available. These are local artifacts, not shipped SDK data.

## Historical LLVM measurements

The remainder predates the independent backend and must not be used as its
current baseline.

Local measurements from 2026-10-04, AMD Ryzen 9 9950X, Linux, LLVM/LLD 23.
The new compiler controls also passed executable regression tests with LLVM/LLD
19, the packaged release toolchain. Times are workload-specific, not promises.

## Compiler findings and decisions

- The earlier DNA hot-helper extraction regressed its synthetic runtime workload
  by about 9% on preview 14 / LLVM 19. Disassembly shows out-of-line helpers in
  the split binary while the same-module binary inlines them. On LLVM 23, remarks
  report `add_text` cost 265 versus O2 threshold 225 and O3 threshold 250;
  `fuzzy_score` remains out of line. Do not force global inlining thresholds or
  promote that extraction. Keep hot helper/caller groups together.
- A fresh LLVM 23 control comparison (five alternating runs) measured 1.001s
  same-module O2, 1.024s split O2, 1.027s split O3, and 0.864s split/native CPU.
  These are not directly comparable to the earlier LLVM 19 timings. Native CPU
  tuning helps that workload but barely changes the std workload below.
- Release builds with debug info explicitly attached `noinline` to every Dyn
  function. This restriction is removed; optimized debug builds can now inline.
- Sample-PGO tests prove LLVM applies body samples and changes hot-call inlining
  decisions. Test profiles are synthetic: no trained DNA PGO speedup is claimed.
  Collection/conversion remains the external profiler's job.
- The existing backend already lowers large value copies through bounded memory
  operations, applies target ABI `sret`/`byval` alignment, and tracks guard facts
  with invalidation across calls/mutations. The regression suite covers these
  seams. No blanket `noalias`, unchecked accesses or lifetime assumptions were
  added: `const` pointers can alias, and incorrect promises would miscompile code.
- No new language syntax or runtime dependency is needed for these improvements.
  Portable O2 stays the default; CPU specialization and O3 remain explicit.

## Standard-library proof

`tests/performance-contracts.py` compares prepared KMP and normal forward/reverse
search against Python byte-search oracles, including empty/binary data and
repeated prefixes. It also checks map reservation/rehashing/deletion/clear,
allocation failure, builder overlap and interleaved allocations, and buffered
write ordering, short writes, partial/sticky errors and every small chunk boundary.

A repeated-prefix search case (32 KiB text, 128-byte needle, 200 searches, five
alternating samples) measured 153.85ms before the tail filter, 3.34ms after, and
15.99ms with prepared KMP. This intentionally pathological case is not an editor
speedup claim. The tail filter remains potentially quadratic; prepared KMP gives
linear search with caller-owned prefix storage for repeated/adversarial searches.

Appending 1,000 single bytes to an initially empty arena-backed builder now uses
1,024 backing bytes instead of retaining successive 64/128/256/512/1024-byte
buffers (1,984 bytes). Interleaved allocations still require copying. Map
reservation avoids intermediate tables; removal/clear still retain key storage.
These contracts are explicit so applications can choose arena lifetimes correctly.

## Repeatable matrix

Run `python3 tools/performance-suite.py --samples 7` to retain JSON samples,
compiler/source hashes, output checksums, executable sizes and child resource use.
The fixture exercises byte search, comparison/copy, UTF-8 decoding, container
operations and builder growth, reporting arena usage/peak/failures. These are
combined workload timings, not independent per-operation throughput figures.

Five-sample local medians, seconds:

| Policy | Cold build | Unchanged | Novel code edit | Runtime |
|---|---:|---:|---:|---:|
| Portable O2 + ThinLTO | 0.189 | 0.040 | 0.100 | 0.173 |
| Native CPU + ThinLTO | 0.206 | 0.039 | 0.102 | 0.172 |
| O3 + ThinLTO | 0.199 | 0.040 | 0.099 | 0.165 |
| O2 without LTO | 0.206 | 0.040 | 0.077 | 0.159 |

All runtime checksums and arena counters match: checksum 322372743, used/peak
12,288 bytes, zero allocation failures. This workload does not justify changing
defaults. Cold means empty Dyn caches, not flushed OS page caches. Reported peak
RSS is an OS per-child maximum, not aggregate concurrent process-tree memory.

## DNA boundary experiment

Move language-server catalog/PATH discovery into `src/servers`, preserving the
existing application entry points and keeping private PATH helpers in that
module. Hot text helpers remain beside their callers. Three novel catalog edits:

| Mode | Before edit median | Extracted edit median |
|---|---:|---:|
| O2 + ThinLTO | 6.362s | 0.569s |
| O2 without LTO | 4.887s | 0.545s |

Single cold samples remain approximately unchanged: 6.508/6.563s with ThinLTO,
4.978/4.944s without. This improves incremental work, not cold compilation.
Catalog/PATH output matches before/after in debug and both release modes.
A five-million-lookup microbenchmark measured 0.163s before and 0.170s after
(five alternating samples, identical checksum). This is a small lookup slowdown,
not zero-cost abstraction; the boundary is retained because catalog discovery
is low-frequency and its edited-build improvement is substantial.
DNA's nine module test suites pass in debug/release; its release UI workflow
smoke test passes with SDL's dummy driver. This is functional proof, not an
interactive responsiveness benchmark.

The DNA change is separate from this compiler repository and sits atop the
user's existing work; unrelated concurrent terminal/scheduler edits were retained.
The old hot-helper extraction remains rejected. More cold-build improvement
requires further compiler/backend profiling, not indiscriminate module splitting.

## Validation

- Full standalone compiler suite, including ABI, unwind, alias-sensitive guards,
  aggregate copying, parser, network, LSP, cache and allocation-failure tests.
- Final focused optimization/cache/std contracts on LLVM 23; optimization and
  sample-profile execution also qualified with LLVM/LLD 19.
- Native host suite; native Windows/macOS validation remains with their CI jobs,
  which now include the new performance contract tests.

Local raw evidence is under `build/performance-work/` (ignored), including
`matrix-final-codegen/`, `search-proof/`, `dna/`, optimization remarks and test logs.
The checked-in fixtures and runners reproduce the compiler/std experiments.
