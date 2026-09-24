> Historical report. Later TAR PAX/GNU, ZIP32 directory/descriptor, and XML namespace/Unicode-name work supersedes the corresponding limits below; see [current format scope](../release/formats.md).

# Lifetime, static-analysis and streaming follow-up

Memory interfaces were subsequently [consolidated into std/mem](mem-consolidation-2026-09-21.md); the separate owner packages and take helpers described below are removed.

This follow-up supersedes the remaining-warning, compression-memory, TAR-result,
CDATA and DNS-transport limitations in the earlier [resolution](resolution-2026-09-21.md).
It does not claim complete lifetime enforcement or full format conformance.

## Compiler and editor

- All four Clang findings are resolved without warning suppression. Filesystem
  stamps hash numeric values in explicit byte order. Cache eviction checks its
  count/list invariant and aborts on internal corruption. Build-job storage is
  initialized with checked allocation sizes. The LSP wire layer receives a count
  value instead of a mutable pointer into document-table bookkeeping.
- `tests/static-analysis.py` analyzes all 26 compiler C translation units and fails
  on warnings or errors. Local Clang 23.1.1 reproduced the original four findings;
  the same command after changes reports none.
- A new zstd stress test exposed an independent compiler bug: fixed-size LLVM
  `alloca` instructions were emitted inside loops. At debug optimization levels,
  each iteration consumed more stack. A standalone two-million-iteration `||`
  loop reproduced SIGSEGV before the fix. Logical operators now merge SSA values;
  every fixed-size slot goes through one entry-block allocation helper, while
  initialization remains at its original evaluation site. Tests also exercise
  enum payloads, case temporaries, foreach arrays, variadic boxing and defer capture.
  This reserves fixed temporary storage per invocation instead of per iteration.

## Ownership and interfaces

- `owned.take` and `growing.take` transfer ownership and clear the source. Existing
  pointers retain their addresses; lifetime now follows the destination owner.
  Raw assignment is still a copy, not a compiler-enforced move.
- `Arena.poison_on_rewind` optionally overwrites reclaimed bytes with `0xDD`.
  Earlier allocations stay intact. This diagnoses some stale use; it does not
  validate pointers or replace lifetime checking.
- Scratch selection detects overlapping backing regions, not just identical arena
  object pointers. Example projects now use pointers to owned arena cursors.
- [Memory contracts](../memory.md#borrowed-results-and-scratch-lifetimes) identify
  borrowed input, output arenas, retained callback state, scratch and native owners.
- TAR's buffered `next` returns explicit Entry/End/Error plus domain error detail.
  Offsets are unchanged on End/Error. Repository callers are migrated. EOF at an
  entry boundary remains supported, without requiring two zero terminator blocks.

## Bounded streaming and interoperability

- DEFLATE and gzip reader adapters share the inflater and reusable-buffer machinery.
  1024 input bytes plus 33026 history bytes support arbitrary valid DEFLATE streams;
  memory no longer scales with file size. Buffered prefix-resume APIs remain intact.
- Gzip streaming accepts concatenated members, consumes arbitrarily long optional
  header fields incrementally, checks FHCRC when present and checks every trailer.
  Trailing nonmember data fails. End requires source EOF; output before End remains
  provisional. Buffered decompression still handles one member and returns consumed.
- zstd streaming uses a static native context in caller-provided workspace, reads
  through a reusable input buffer and writes directly to caller output. Workspace
  sizing and maximum window are explicit. No native heap allocation/free is used
  for this context. Concatenated frames work; truncation and window excess fail.
  Its advanced provider ABI was tested against installed zstd 1.5.7.
- XML adds literal `Kind.Cdata` events to buffered and stream scanners, with split
  delimiter tests and document-level character/placement checks.
- DNS adds A/AAAA queries sharing parser and transport implementations, plus TCP
  fallback for truncated/oversized UDP responses. Nonblocking connect and partial
  transfers share a timeout budget and caller packet storage. SO_ERROR support
  includes the AArch64 syscall mapping. The DNS server transport address is IPv4.

Wire-format references: [DEFLATE](https://www.rfc-editor.org/rfc/rfc1951),
[gzip](https://www.rfc-editor.org/rfc/rfc1952),
[XML CDATA](https://www.w3.org/TR/xml/#sec-cdata-sect),
[DNS framing](https://www.rfc-editor.org/rfc/rfc1035), and
[DNS TCP transport](https://www.rfc-editor.org/rfc/rfc7766).
Native zstd contracts were checked against installed `/usr/include/zstd.h`.

## Validation

Workspace logs are in `build/lifetime-followup/`. Completed checks: full compiler
suite; all SDK fixtures and library contract suites; sanitizer compiler suite;
new streaming and DNS cases compiled under ASan/UBSan; editor/Neovim checks;
per-file compiler build; and 109 SDK/project module checks with zero failures.
Typed metamorphic checks passed 192 builds; fuzzing passed 136 source versions
through compiler and incremental/full LSP analysis. GPU execution was reported
unavailable. New regression gates include:

- `tests/loop-stack` debug/release, also included in the sanitizer compiler suite.
- `tests/sdk-lifetimes`, automatically included in the SDK fixture runner.
- `tests/streaming-window.py`: independent zlib/gzip reference data, stored/fixed/
  dynamic blocks, one-byte input, long optional headers, concatenation and corruption.
- `tests/zstd-streaming.py`: 4.8 MB native reference through 113-byte input storage,
  one-byte source reads, concatenation, truncation, workspace and window limits.
- `tests/dns-transport.py`: loopback UDP/TCP, A/AAAA, wrong IDs, split frames,
  timeout, early close and caller-capacity failures, in debug/release.
- `make test-static-analysis`: all C compiler units, zero warnings.

The new codec and DNS scripts are part of `make test-libraries`.

## Still deliberate limits

No full borrow checker or noncopyable type system; debug poisoning cannot detect
all lifetime errors. Native handles still require explicit ownership discipline.
TAR PAX/GNU extension interpretation, ZIP64/encryption/data descriptors/full central
validation, XML DTD/namespaces/Unicode names, DNSSEC/cache/iterative resolution and
IPv6 DNS-server transport remain outside supported scope. JSON/regex depth bounds
remain intentional. Windows/macOS native execution, GPU execution and publication
of the refreshed Zed grammar are still external validation/release work.
