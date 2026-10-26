# Application and std-library comparison

These are working small applications, not arithmetic kernels: a JSONL log reporter, a recursive byte-text search tool, and a local HTTP/JSON summary service. The same inputs produce the same checked outputs. They are not ports of complete production products and do not establish a language-wide ranking.

Run from the compiler directory:

```sh
python3 tools/app-comparison/check_harness.py
python3 tools/app-comparison/run.py
python3 tools/app-comparison/project_search.py
python3 tools/app-comparison/report.py
```

Results default to `build/app-comparison-20261024/`. The project-search and report helpers use that default directory. `run.py --check-only` checks the implementations without timing. Its `--rounds`, `--http-rounds`, `--records`, and `--files` options control experiment size. Do not run other builds or benchmarks during timing.

## Prerequisites and implementation choices

Linux, an existing `build/dyn-release`, GCC, host Clang, Rust/Cargo, Go, Node, Python, pkg-config, yyjson headers/library, a C compiler for the RSS helper, and taskset are required. Cached Cargo dependencies must include the pinned serde_json release; Cargo runs offline. Missing prerequisites fail explicitly. Nothing installs dependencies.

Dyn, Go, Node, and Python use their std libraries. C uses the installed yyjson library; Rust uses serde_json's generic DOM. Their versions are recorded. Both GCC and Clang compile the same C source. HTTP compares only the four std-server implementations; no external C/Rust HTTP framework was chosen.

Dyn uses a checked unsigned-integer reader for normal integer tokens and the general floating reader for fraction/exponent spellings. This preserves the shared numeric validation contract. The earlier all-f64 Dyn experiment is retained separately in `generic-number-baseline/` in the recorded experiment directory; it is not the final port. The initial comparison made no compiler or std implementation changes. A subsequent general optimization pass improves allocation, JSON string handling, integer parsing, file reads, and trusted x86 byte searches; the application implementations remain unchanged.

Rust's search uses standard slice windows for byte substring matching. Other ports use their ordinary byte-search primitives. Go's directory walker, Node's per-path metadata calls, parser representations, allocation strategies, and HTTP schedulers differ. These are application/library comparisons, not identical generated-code experiments or optimized production-tool comparisons.

## Measurements and limits

The CLI corpus contains 60,000 JSONL records, and a separate 1,024-file/64-MB text tree. A second search run snapshots actual compiler/std sources, preserving file bytes while appending `.txt` to names. Every result is checked against an input-derived oracle. CLI times include process startup and file I/O on a warm filesystem cache, with two warmups and nine rotating samples per implementation.

HTTP uses a 64-record JSON request, one server CPU, separate client CPUs, and a new loopback connection for every request. Each of five rounds starts a fresh server, warms it with 100 requests, measures 100 single-client requests, then 300 requests across four clients. Every response is checked. Throughput includes client validation overhead. Sample p95 latency is not a tail-latency guarantee. Persistent connections, TLS, databases, persistence, overload behavior, native Windows/macOS, and multi-core scaling are not qualified.

Numeric validation uses parsed binary64 integral values up to 2^53-1. Duplicate-key and invalid-UTF-8 policy differences are outside the supported corpus. See `SPEC.md` for the complete contract. Build times are recorded as observed, including dependency/incremental-cache effects; they are not a compile-speed ranking. Executable sizes exclude shared libraries and interpreter/runtime installations. RSS is measured, not reserved virtual address space.

## Std findings exposed by these applications

The current Linux std has the APIs needed for all three applications. The initial comparison exposed a lazy-arena initialization problem in `fs.read_all`. The subsequent pass fixes it while retaining bounded fixed-buffer Capacity results and rollback. The original `std-probe/` remains historical evidence.

Directory iteration used here is Linux-specific. Filesystems returning unknown directory entry types fail explicitly in the Dyn port. A portable directory walker and no-follow metadata support would make this application less platform-specific.

The general decimal-to-f64 path is expensive for ordinary integer fields; using the integer API makes a large measured difference. JSON and file-search performance still vary substantially against the other libraries. File reading now uses bounded 64-KiB chunks. Optimized x86 direct calls to the trusted SDK byte-search functions use bounded SSE2 loads; scalar bodies remain available for tree emission, indirect calls, and other targets. Guarded-page tests cover both Linux and Win64 under Wine. Current JSON parsing retains the public owned DOM; a two-pass allocation-pooling experiment was slower and was rejected.

The results support “usable for these Linux applications,” not “uniformly fast or fully production-qualified std.” Existing DNA qualification remains separate evidence for a larger application.
