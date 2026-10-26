# Application comparison contract

This is an application/library comparison on Linux, not a universal language ranking. No compiler or std changes are part of this benchmark. Inputs are generated independently; all successful outputs are compared structurally against Python-generated integer oracles. All implementations must use a real JSON parser, not scan known text positions.

## CLI applications

Each language implementation has two modes: `report FILE` and `search DIRECTORY`. Failures exit nonzero; no partial success JSON is published.

`report`: read the complete JSONL file, split on LF (accept final unterminated record; ignore empty lines), parse each record as a JSON object. Read required `service`, `status`, `bytes`, `latency_us`. Service is exactly one of `svc00` through `svc15`; each numeric field is a nonnegative integer <= 2^53-1 (status <=599). Integer validation applies to the parsed binary64 number, including semantic integers written as 1.0/exponents and negative zero; decimal fractions rounded to integral binary64 are accepted. Reject wrong types, missing fields, unknown services, malformed JSON. Aggregate and per-service counters must remain <= 2^53-1. Duplicate object members are outside the supported schema; the corpus contains none, and parser duplicate-key policy differences are not ranked. Other fields are parsed normally but ignored. Aggregate records, bytes, latency_us, and errors (`status >=500`). Per-service arrays, in svc00..svc15 order, contain `[records,bytes,latency_us,errors]`. Output one JSON object:

`{"records":N,"bytes":N,"latency_us":N,"errors":N,"services":[[N,N,N,N],...16 entries...]}`

Use ordinary DOM JSON APIs for all implementations. Dyn uses std/encoding/json; C uses installed yyjson; Rust uses cached serde_json::Value; Go uses encoding/json; Node JSON.parse; Python json.loads. No typed-deserialization or simd-specific alternate path. Each implementation may release/reuse per-record allocations idiomatically. No deliberate duplicate application work.

`search`: recursively visit directories, no symlink following. Only regular files whose basename ends in `.txt` are read. Read each selected file completely and examine byte lines (LF split, trailing LF does not create another line). Count a line once if it contains ASCII byte substring `ERROR`. Empty file has zero lines; consecutive LF creates empty lines. Count files, bytes, lines, matching_lines, matching_files. Output exactly these five integer keys in one JSON object. Traversal order is irrelevant; results commute. No regex, external grep, or shell process. File contents are arbitrary bytes. Use each standard library's substring/search primitive (C memmem is allowed on Linux); no custom SIMD.

## HTTP application (Dyn, Go, Node, Python)

Bind loopback port0 and print `port N` to stdout, flushed. Four client connections are used in the concurrent workload; every request carries Connection: close. Native server implementations use standard HTTP parsers/servers; Dyn four concurrent workers, Python ThreadingHTTPServer, Go net/http, Node http. Pin server to one common CPU; client runs elsewhere. This measures the chosen std server designs, not identical schedulers.

GET /health returns 200 `ok\n`. POST /summarize parses a JSON array of objects using the same schema and aggregation as report, returning the same summary JSON and application/json. Malformed JSON/schema returns400. Unknown GET/POST route returns404. Other methods are not compared. The corpus uses valid UTF-8 and duplicate-free object members; invalid-UTF-8 and duplicate-key policies differ between JSON libraries and are not ranked. Content-Length body limits are 1MiB; benchmark payloads much smaller. POST /quit sends200 and shuts down cleanly. No TLS, compression, database, or persistence. The load runner validates every status/body; client errors/timeouts are failures, never discarded samples.

## Measurement

Compiler/toolchain versions, command lines, source hashes, libraries, inputs, binary sizes, build wall time, and maximum RSS are recorded. Release optimized baseline x86-64 settings; no fast-math or native-only tuning. CLI timing includes startup and I/O on warm filesystem cache, nine rotating rounds after two warmups. HTTP startup and steady-state are separate, with both one-client latency and four-client throughput/latency. Tail values from this bounded local test are sample percentiles, not service guarantees. All runs bounded; server processes cleaned on success/failure. No concurrent benchmarks/builds during measurement.
