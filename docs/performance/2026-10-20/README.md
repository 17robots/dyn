# Independent compiler qualification, 2026-10-20

These measurements qualify the independent compiler after PR #121. They do not
establish universal parity with LLVM. Native timing results for other machines
are produced as JSON artifacts by the Runtime benchmarks workflow.

## Linux x86-64 runtime

Seven-sample medians, default Dyn release, GCC 16.2 `-O2`, Go 1.27.2. Each kernel
prints the same checksum in all three languages. Runs include process startup;
short kernels are particularly sensitive to it. No CPU affinity or frequency
locking was applied. See `kernels.txt` for the complete measured table.

The added aggregate snapshot lowering exposes small private copies to SSA
forwarding. In seven alternating pairs of the points kernel with 20,000 rounds,
the median changes from 125.62 ms at PR #121 to 109.86 ms, a 12.5% reduction.
Every pair has identical output. Raw samples are in `points-paired.json`.

The usual 2,000-round points workload is about 1.28 times C's runtime; sieve is
about 1.23 times C. Their remaining gaps have not been eliminated. Sieve's
initialization still uses a scalar byte loop; no unproved optimization is enabled
based on that observation alone.

DNA's release executable remains 1,564,040 bytes. Its text grows 144 bytes relative
to PR #121. Debug/release application memory and latency need separate measurement
from file size and kernel throughput.

## DNA application comparison

`tools/bench/dna.py` reuses DNA's existing two-round workflow and rendering
checks. It alternates baseline and candidate binaries, saves logs and binary
hashes, and reports input latency and RSS. It does not interpret deliberate
harness waits as application throughput. Build both binaries from identical DNA
sources and dependencies before running it:

```sh
python3 tools/bench/dna.py --project /path/to/dna \
  --baseline /path/to/llvm-built-dna --candidate /path/to/independent-dna \
  --dyn build/dyn-release --sdk . --output build/dna-comparison
```

The initial three-pair PR #121 comparison against the retained LLVM compiler
measures median mean input latency of 2.708 ms versus 2.764 ms (2.1% longer).
Median final RSS is 44,956 KiB versus 50,992 KiB (about 5.9 MiB higher).
Both variants pass identical rendering and workflow checks. Compiler runtimes and
standard libraries follow their respective SDKs; this is an end-to-end SDK
comparison rather than an isolated machine-code-only experiment. Three samples
are insufficient to establish a small latency regression conclusively. Startup
mapping inspection locates additional memory mainly in anonymous mappings and
stack pages; it does not establish the allocation source.

The final candidate rerun is recorded in `dna-workflow.json`: median mean input
latency is 2.677 ms baseline and 2.678 ms candidate, effectively equal. Median
final RSS is 44,108 KiB baseline and 53,092 KiB candidate (about 8.8 MiB higher).
The earlier and final measurements show the memory gap varies by run. Reducing
that gap needs allocation-level profiling; the snapshot optimization does not
claim to fix it. Every workflow and rendering check passes.

## Reproducible target benchmarks

`tools/bench/runtime.py --stage build/runtime-benchmarks` compiles the five kernels
for every supported target and derives checksums from host C builds. The staged
runner verifies executable hashes and every sample's checksum. CI uploads raw
samples, medians, executable sizes, compiler hashes, target and host metadata.

Browser kernels export the checksum instead of using standard output. Browser
page creation and module compilation are included; browser launch is excluded.
WASI timings include Node startup and module compilation. RISC-V QEMU results are
explicitly emulated and must not be presented as hardware throughput.

## Correctness and cache qualification

The differential corpus bounds work-dependent inputs while retaining full-width
arithmetic and C ABI values. Range starts still include integer extrema; endpoints
remain nearby. Every timeout now fails qualification, including a matching pair
of timeouts. AArch64 seeds 1 and 2 and RISC-V seed 2 pass with zero timeouts;
437/457 panic cases depend on the seed. Linux x86-64 seed 1 also passes.

Cache tests cover source/dependency/options/runtime invalidation, malformed
metadata, a killed writer, recovery, and eight actual builds sharing a cold cache
with four concurrent producers. No production cache bug was reproduced.

The release bundle validator now requires Windows ARM64 and macOS x64 evidence
in addition to the three previously required native reports. RISC-V and release
ARM64 differential checks remain enforced through release workflow dependencies.
