# Constant-table compiler performance

## Cause and change

`static_value` refused any nonempty constant array longer than 4,096 elements.
The generated Unicode tables exceed this threshold. Their initializers therefore
became thousands of runtime stores, which LLVM then had to optimize and emit.
This was a code-generation representation problem, not Unicode normalization cost.

Fully populated constant arrays now use the existing LLVM constant initializer
path regardless of that cutoff. Sparse large arrays retain the bound, avoiding
expansion of enormous zero tails into compiler-side element lists. Empty arrays
still use LLVM's compact zero initializer. Runtime expressions still fall back to
runtime initialization. No SDK API, arena policy, optimization level, or correctness
check changes.

## Measurements

Run `python3 benchmarks/compiler-phases.py --output REPORT.json` before/after on
this Linux host, three fresh invocations per workload/mode, one compiler job,
no build cache. Raw records and compiler binary hashes are retained in
`build/compiler-perf/before.json` and `after.json`. These are host-specific medians,
not performance guarantees. Small workload differences should be treated as noise.

| Workload | Mode | Before ms | After ms | Before RSS MiB | After RSS MiB |
| --- | --- | ---: | ---: | ---: | ---: |
| modules-4-functions-25 | check | 8.7 | 7.4 | 30.7 | 30.7 |
| modules-4-functions-25 | debug | 16.7 | 13.1 | 49.4 | 49.6 |
| modules-4-functions-25 | release | 9.7 | 10.5 | 57.9 | 57.7 |
| modules-20-functions-50 | check | 31.2 | 31.5 | 34.4 | 34.7 |
| modules-20-functions-50 | debug | 84.2 | 85.2 | 60.1 | 59.4 |
| modules-20-functions-50 | release | 43.0 | 42.9 | 63.8 | 64.1 |
| sdk-unicode | check | 326.2 | 322.4 | 92.3 | 91.8 |
| sdk-unicode | debug | 459.0 | 359.5 | 162.5 | 114.0 |
| sdk-unicode | release | 2403.3 | 387.8 | 414.0 | 128.6 |

## Regression coverage

`tests/constant-array-codegen.py` failed before the fix because an 8,192-element
constant table emitted runtime initialization. The test checks compact static IR,
an independently computed runtime checksum, a 64 MiB sparse array's zero tail,
imported constants and dependent global initialization, separate module emission,
cache reuse, and debug/release execution. It is part of `make test-contracts`.

Validation logs: `build/compiler-perf/`. Native platform tests remain excluded.

Passed: new constant-array regression; 403,031 Unicode conformance vectors in
both modes; 192 typed metamorphic builds; compiler contracts and bounded-stack
stress; all SDK fixtures in debug/release; separate C translation-unit build;
26-unit static analysis with zero warnings; frontend/allocation-failure tests.
ASan/UBSan compiler runs passed the constant-array regression and full Unicode
conformance suite. Generated Dyn executables were run normally; this does not
claim sanitizer instrumentation of those executables.

For the Unicode release workload, median LLVM optimization time dropped from
964 ms to 39 ms and emission from 1,080 ms to 20 ms. Source loading and semantic
analysis stayed approximately unchanged, confirming the representation hypothesis.
