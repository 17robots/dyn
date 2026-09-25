# Dyn/C benchmarks

Fair microbenchmarks for the C compiler's release output. Every pair must emit
the same checksum before it is timed. C `stdio` variants measure conventional C;
`matched` variants use the same buffering/algorithm as Dyn.

Run:

```sh
./benchmarks/run.sh 15
```

Compile-time scaling for empty fixed arrays is measured separately:

```sh
./benchmarks/compile-scale/run.sh
```

It checks 1 KiB, 1 MiB, and 64 MiB arrays and reports compiler wall time and emitted IR bytes.
IR size should remain approximately constant rather than following storage size.

Incremental compiler latency (clean, unchanged, private dependency edit):

```sh
./benchmarks/compile/run.sh 11
./benchmarks/compile/run.sh 7 --check
```

Regression gate (21 medians; matched Clang):

```sh
./benchmarks/check.sh
```

Gate allows 10% for compute and formatting, 50% for streamed I/O, and 3x for
arena allocation because Dyn retains bounds, alignment, and overflow checks that
the matched C loop omits. Stripped static Dyn arena output has a 64 KiB ceiling;
comparing it directly to dynamically linked C file size would be misleading.
Thresholds catch large changes, not ordinary host noise.

`CC` selects the C compiler. Dyn uses LLVM, so `CC=clang` gives the closest
backend comparison; the default `cc` shows the platform's ordinary C toolchain.

Results are TSV: workload, implementation, median wall/user/system seconds,
median peak RSS KiB, and stripped bytes. Close values are ties; this suite does
not claim that either language is universally faster.

An optional same-output compute comparison includes every installed C, Go, Zig, and Odin toolchain:

```sh
./benchmarks/languages.sh 15
```

It records toolchain versions externally with benchmark results; missing compilers are skipped.

Compiler phase and memory baseline (Linux/macOS host, Python 3):

```sh
python3 benchmarks/compiler-phases.py --output build/compiler-phases.json
```

Uses three fresh no-cache invocations per workload/mode, one compiler job, generated
100/1,000-function module trees and the Unicode SDK fixture. Records raw samples,
median wall milliseconds and peak RSS KiB. A fresh measurement helper isolates each
invocation's resource high-water mark. RSS includes waited-for compiler children;
it is not the sum of simultaneously live processes. Host load affects results.

`dyn --timings` retains load/check/codegen/link totals and adds `timing detail`
records for parse, AST lowering, semantic analysis, typed IR, LLVM generation,
optimization and emission. Detail records are nested within totals, not additive
to them. Parsing during module loading remains in `load`; `detail parse` measures
analysis tree acquisition/validation. Parallel modules can overlap; sum details as
worker time, not wall time. Normal commands emit no timing records.

Larger incremental builds and LSP edits:

```sh
python3 benchmarks/incremental-project.py > build/incremental-project.json
python3 benchmarks/frontend-work.py > build/frontend-work.json
```

Both accept `DYN=/path/to/compiler`. The incremental benchmark uses an isolated
cache and 13 modules, recording one cold build and seven samples each for unchanged
builds, private-body edits, and public-interface edits. It runs each resulting
binary and records module/interface cache hits. Public-interface changes invalidate
transitive importers; unrelated module objects remain reusable. Reflection retains
conservative project-wide content dependencies because type metadata can depend on the
whole project.

The frontend benchmark records fresh builds, 20 serialized real edits, and 20
bursts of ten queued edits against a 300-function dependency. Edit latency includes
diagnostics and the following document-symbol response. Run benchmarks without
concurrent builds or tests.

Build the optimized compiler with `just release`, then select
`DYN=./build/dyn-release`. The ordinary `build/dyn` remains a debug compiler;
`just install` installs the optimized compiler. Dyn's own `--release` option
controls optimization of the generated program independently.

Compiler scaling and performance regression checks (Linux, GNU-compatible linker):

```sh
just perf-compiler
python3 benchmarks/compiler-scaling.py --output build/scaling-baseline.json
python3 benchmarks/compiler-scaling.py --baseline build/scaling-baseline.json \
  --output build/scaling-current.json
```

Workloads cover 8–128 imports, 32–512 struct fields, and 128–4,096 qualified
references. Five samples per size record median/max wall time and median peak RSS.
An instrumented `build/dyn-perf` counts allocation calls and requested bytes in
compiler/generated-parser code; shared LLVM/Tree-sitter/libc allocations are
excluded. Requested bytes include realloc requests, not live memory. RSS covers
the entire process. `DYN` and `DYN_PERF` override the two binaries.

Editor measurements report median, p95, and maximum latency for individual edits
and bursts. The gate allows 35% + 2 ms for compiler time, 25% + 4 MiB for RSS,
15% + 100 allocation calls, 25% + 4 KiB requested bytes, and 50% + 2 ms for editor
p95. Keep baselines on the same host/configuration; inspect noisy failures before
changing thresholds. Protocol ordering checks run alongside timing measurements.

Focused wide-function regression gate:

```sh
just release
python3 benchmarks/large-function.py --verify --output build/large-function.json
```

Measures 1,024 and 4,096 qualified calls, direct calls, and local declarations
with three samples per size. Reports phase timings and compiler identity. The
gate rejects fourfold workloads taking more than eightfold time plus 20 ms;
the local-heavy workload additionally checks semantic-analysis scaling with a
2 ms allowance. This catches the previous quadratic binding scans without a
machine-specific absolute time threshold. `DYN` selects another compiler.

Repeated type/member access and debug metadata scaling:

```sh
python3 benchmarks/member-work.py --verify --output build/member-work.json
```

Measures 256/2,048 distinct types, repeated accesses across wide structs, and
locals with debug information. Keeps raw phase samples and compiler identity.
The gate allows sixteenfold semantic/LLVM-generation time for eightfold input,
plus 0.5/2 ms respectively. It detects the former quadratic field lookup and
debug-local metadata work without constraining LLVM's optimization settings.

Isolated build scheduling (synthetic, four jobs; two expensive jobs would occupy
one old round-robin lane):

```sh
cc -std=c11 -O2 -Icompiler/src benchmarks/build-scheduling.c compiler/src/build.c -o build/build-scheduling
build/build-scheduling > build/build-scheduling.json
```

Compares the former fork/round-robin policy against the current scheduler.
Single-worker samples run 100 empty plans to isolate process overhead; two-worker
samples use 40/1/40/1 ms jobs. Actual build gains depend on module cost balance.
