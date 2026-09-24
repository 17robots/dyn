# Security model and review checklist

Dyn keeps allocation, ownership, foreign calls, and unsafe pointer conversion visible. Bounds,
nil, alignment, shift, division, and integer-overflow checks remain enabled in release builds unless
the compiler proves them redundant. Arenas improve lifetime organization but do not prevent stale
slices, aliasing mistakes, data races, or incorrect foreign layouts.

Trust boundaries:

- Parsers accept hostile source, JSON, URLs, HTTP, WebSocket, archive, regex, CLI, and environment
  bytes. They must bound lengths, reject overflow/noncanonical encodings, and use caller storage.
- TLS delegates cryptography and certificate validation to OpenSSL; callers must check every result,
  configure hostnames, and destroy owned provider objects.
- FFI and `rawptr` are unsafe boundaries. Generate bindings from the exact target headers, validate
  sizes/alignment, and never infer union, bitfield, callback, or ownership semantics.
- Filesystem paths and process arguments are untrusted capabilities. Canonicalize dependency roots,
  reject traversal, avoid shell interpolation, and use explicit descriptors/argument arrays.
- Concurrent code must synchronize shared mutable memory. Arenas are not thread-safe unless an
  application supplies synchronization or partitions ownership.

Release checklist: run `just quality-c`, `./projects/validate.sh`, `./tests/release-gate.sh`, review
new `rawptr`/`#syscall`/foreign declarations, fuzz changed parsers, and test every affected native
target. Security-sensitive APIs document borrowing, ownership, capacity, provider errors, and any
data-dependent behavior. Dyn is pre-1.0 and has not received an independent security audit.

## Candidate audit evidence

The 0.1 readiness work reproduced and fixed two compiler trust-boundary failures:
8192 nested groups could overflow the C stack, and a foreign three-word struct
passed by value produced an incorrect runtime result. A shared iterative syntax
check now prevents recursive consumers from seeing trees over 1024 levels; CLI
text/JSON and LSP recovery tests exercise that boundary. C-compatible struct calls
now use shared target ABI lowering; Dyn-only foreign storage fails before code
generation. Aggregate probes cover direct/indirect calls and callbacks. Raw pointer
adapters remain subject to layout and lifetime validation. These are specific fixes,
not a whole-program safety proof. Cooperative work budgets and cancellation bound
frontend work; blocking filesystem calls remain outside that deadline mechanism.

The existing fault-injection tests exercise allocation/read failures, while sanitizer
fuzzing compares compiler and incremental/fresh editor behavior. The readiness soak
adds contention/condition/semaphore/once and repeated storage/archive/database/process
execution. Keep run counts, seeds and duration with results. Neither a short soak nor
known-answer crypto tests establish resistance to all adversarial inputs or replace
an independent review. Source compilation and LSP operation are not sandbox boundaries.

Release evidence and unresolved native/provider/editor checks live in
[the readiness checklist](release/readiness.md). Public API reference counts are
an audit navigation aid, not a security or behavioral coverage percentage.
