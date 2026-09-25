# Library contracts and migrations

## Canonical I/O

Use `io.read`, `io.write`, `io.read_exact`, and `io.write_all`. Removed redundant
`reader_read`, `writer_write`, and `read_full` public aliases; callers and SDK fixtures
now use the canonical names. Private adapter callbacks are implementation details.

Empty reads/writes succeed without invoking a callback. Results cannot report more bytes
than the supplied slice. Error results always carry a nonzero error code. Readers may
return bytes together with EOF or an error; writers cannot report EOF. Exact-read and
write-all helpers preserve partial progress and reject stalled operations.
Buffered writers retain only unwritten bytes after a partial flush failure, with a sticky
error preventing accidental replay.

## Arena and provider ownership

Dyn-owned heap storage comes from std arenas. Caller-buffer APIs can use stack storage
or arena slices. Provider handles are a separate explicit ownership boundary:

- SQLite `open(name, buffer)` uses temporary caller C-string storage. Failure returns
  no handle and closes any partially created database. Successful opens require `close`.
  A failed close retains ownership and must be retried after releasing outstanding resources.
  Error messages borrow the database until its next call or close.
- TLS provider handles and borrowed results follow [TLS](tls.md).
- zstd and OpenSSL crypto results report `written = 0` on failure; provider error codes
  are diagnostic values, never byte counts. Output may have been modified and must be discarded.
- Arena-backed zstd operations rewind their own allocations on failure and preserve earlier
  allocations. The streaming decoder uses caller-owned input storage and static provider workspace;
  see the streaming migration below. One-shot arena helpers retain their existing contracts.

SQLite's failed-open ownership rule is specified in
[sqlite3_open](https://www.sqlite.org/c3ref/open.html).

## Compiler lifetime checks

Directly returning an address of a local (including a by-value parameter), a slice of a
local array, or a literal aggregate containing such a borrow is rejected. Borrowed
pointer/slice parameters and references to globals remain valid. These are narrow
syntactic diagnostics: aliases, calls, stored aggregates and arena resets are not tracked.
The language does not yet enforce a complete borrow/lifetime model.

## Validation

`just test-libraries` requires pkg-config and OpenSSL 3, SQLite 3, zstd and Vulkan
development libraries (SDL3 is optional). It builds and runs SDK fixtures in debug and release against current
canonical std/vendor imports. SQLite, zstd and OpenSSL crypto use installed native providers;
TLS also has a deterministic provider for failure ordering and ownership tests. SDL3 runtime
is explicitly skipped when unavailable, with semantic checking retained. CI installs required
providers and records versions; native provider fixtures run on Ubuntu 22.04 and 24.04. Windows/macOS native CI also executes owned-arena probes.
These new CI jobs have not been executed from this local session. Local validation used
OpenSSL 3.6.4, zstd 1.5.7, SQLite 3.53.4 and SDL3 3.4.16 on Linux x86-64.
Provider-version compatibility beyond executed versions remains unverified.

## Further SDK interface cleanup

- Removed `mem.arena_init`, `arena_reset_to`, and `arena_child`; use `arena_from_buffer`,
  `arena_rewind`, and `arena_sub`. All repository callers, including benchmarks, are migrated.
- `arena_try_sub` now returns `ArenaResult`; inspect `ok` then consume `.arena`.
  `Allocation` adds domain `error` and native `code` fields.
- `flags.usage` and `completion` return `TextResult`; inspect `.ok`, then use `.value`.
  `.required` reports exact capacity; empty successful completion is unambiguous.
- Base32 now uses `encoded_size` like hex/Base64. Replace `decoded_length` with the checked
  `decoded_size(source, &size)`. All three decoders reject malformed input without partial writes.
- Codec, string and C conversion results include failure detail; C string adapters reject NUL
  inside input. Caller-buffer string clone/join/split interfaces back the arena conveniences.
- SQLite gains bound statements and typed row access; see [SQLite](sqlite.md).
- Added [arena-backed collections](collections.md). See [buffer contracts](buffer-contracts.md)
  for capacity, overlap, partial-output and lifetime rules.

## September 2026 audit changes

- Removed unused `std/errors`. Keep errors at their domain boundary; translate
  them explicitly where an application needs one result type.
- Removed HTTP stream forwarding helpers (`stream_read`, `stream_write_all`,
  `stream_failed`, `stream_ended`) and response field accessors
  (`client_response_raw`, `client_response_body`, `client_response_status`). Use
  `std/io` operations/status and response `.raw`, `.body`, `.status` fields.
- `dns.parse_ipv4(packet, id, expected_name, addresses)` now requires the original
  question name. It rejects mismatched questions, truncated responses, bad
  compression references, and reports address-capacity exhaustion. The resolver
  uses random transaction IDs and detects oversized UDP replies. It supports
  A and AAAA queries over UDP with TCP fallback using an IPv4 DNS server address.
  DNSSEC validation and caching remain absent.
- HTTP heads expose explicit None/Length/Chunked/Close framing. Unsupported
  transfer codings and conflicting TE/CL headers fail. The client handles interim
  responses, HEAD/no-body statuses, close-delimited bodies and terminal chunks.
  A query-only URL is rendered with the required leading `/`.
- HTTP workers require `stop(workers)`, then `join(workers)`, then closing the
  listener. Shutdown interrupts blocked socket operations, not arbitrary handler
  computation. A bad request increments `request_errors` and keeps the worker
  available. Partial startup stops/joins earlier workers; `started` records how
  many had started, not how many remain live. Stacks, workers and buffers must
  remain disjoint and alive through join. Read counters after joining.
- `fs.File{}` borrows descriptor zero (stdin); it is not a closed owner. Use
  open/create results and close the same owning slot. Copies do not duplicate
  descriptors. Paths reject embedded NUL on all platform adapters. Linux file
  identity/size metadata uses `statx` (Linux 4.11+); `read_all` reads one open
  descriptor to EOF, with explicit maximum/capacity and arena rollback on failure.
  Copy rejects identical file identities before truncation, including hard links.
- Slot-map initialization advances generations. Generation `UINT32_MAX` retires
  a slot instead of wrapping. Zero generation backing only once before first use;
  do not manually reset it while handles exist. Handles do not identify a map
  instance; using one with unrelated backing is invalid.
- Compact JSON encoding is bounded to depth 256; regex compilation reports
  `CompileError.Depth` above 128 nested groups. Runtime unwind registration
  supports 64 simultaneously registered threads and panics explicitly on overflow.
- Text and HTML templates share parsing, lookup and retention. HTML escaping is
  for text and quoted attribute values, not JavaScript, CSS or URL sanitization.

## Format and streaming limits

TAR supports checksum-validated V7/USTAR, PAX path/linkpath/size overrides, and
GNU long-name/link records. Use `state := tar.reader(archive)` then `tar.next(&state)`;
this replaces `next(archive, &offset)` so global PAX state persists. End/error leave
reader state unchanged. EOF at an entry boundary remains accepted. GNU base-256 and
sparse payloads are unsupported. PAX unknown keys are ignored; metadata is consumed
internally. The streaming constructor takes a third argument, metadata `[]u8`
(replacing the short-lived arena-pointer interface). Pass a stack buffer or a
slice allocated from an arena; an empty slice reports Capacity on extended metadata.
The storage is split into two equal reusable banks; each must fit live global/local
names plus the next metadata payload. All names borrow header/metadata storage until
`next_stream`. Header and metadata storage must be disjoint.

ZIP adds `open_checked(source)`: validate ZIP32 central-directory framing, counts,
local-header names/flags/method/sizes, and optional signed/unsigned data descriptors.
Pass its `.reader` to `next`. Payload CRC and exact DEFLATE consumption are checked
by `extract`. Existing `open`/`next_stream` remain explicitly local-entry readers;
they do not claim full archive validation and reject data descriptors. ZIP64,
encryption, split archives and self-extracting offset correction remain unsupported.
No reader writes archive paths onto disk; extraction policy belongs to the caller.

XML supports XML 1.0 Fifth Edition Unicode names, UTF-8 values, quoted attributes, predefined/numeric
entities, CDATA, comments and processing instructions. `valid` checks nesting, attribute
syntax/duplicates and character/entity validity. It is not full XML conformance:
DTD/entity declarations remain absent. Namespace resolution is explicit through
`namespaces`, `namespace_enter`, `namespace_resolve`, and `namespace_leave`, using
caller binding/frame/byte buffers. Enter self-closing tags, inspect attributes,
then leave them immediately; ordinary tags leave on their End event. Failed enter
restores context state. Namespace checking complements `valid`; it does not change
`valid` into a namespace-aware document validator.
CDATA events use `Kind.Cdata` and preserve literal text without entity expansion;
CDATA is allowed only inside the document element when using `valid`.
The attribute scanner borrows an event's attributes including leading whitespace;
its error distinguishes malformed attributes from completion. Stream events
borrow storage until the next call; text event boundaries depend on input chunks.

DEFLATE/gzip reader adapters reuse input storage and retain at most the last 32 KiB
of output history between batches. Supply 1024 compressed-input bytes and at least
33026 history bytes for arbitrary valid DEFLATE streams. Smaller buffers can serve
smaller streams, but may report capacity errors. Memory usage no longer scales with
file size. Buffers, decoder state and read destination must be disjoint and alive.

Buffered `resume`/`resume_gzip` still require unchanged, monotonically growing
prefixes. Buffered gzip decompression handles one member and reports `consumed`.
The gzip reader handles concatenated members through source EOF, verifies every
header/member CRC and size, and rejects trailing nonmember bytes. Reader output is
provisional until End. Errors are sticky; empty reads do not consume input.

zstd `decoder(input, compressed_bytes, workspace, window_log)` now streams into the
read destination. The former output-storage argument becomes provider workspace;
allocate `decoder_workspace_size(window_log)` bytes from an arena or stack buffer.
The constructor aligns the context internally. `window_log` is 10–30 and bounds
accepted frame history to `2^window_log` bytes. Larger-window frames fail explicitly.
Workspace remains borrowed through the decoder's last use, with no native free call
or hidden heap allocation. Concatenated frames are supported, truncation fails,
and outputs remain provisional until End. The provider's static-context interfaces
are advanced zstd ABI; the local validation used zstd 1.5.7.

Arena ownership is conventional. Rewind/reset/release invalidates borrowed slices;
copied native owners are unsafe. No complete compiler borrow checker is claimed.
The C compiler's own allocation strategy is independent of Dyn's arena policy.

## Lifetime and transport follow-up

- Keep arenas in their creating scope and pass pointers rather than copying
  their cursors. Heap backing is part of `mem.Arena`; no separate owner is needed.
  See [memory contracts](memory.md#borrowed-results-and-scratch-lifetimes).
- `Arena.poison_on_rewind` opt-in scribbling covers only reclaimed allocations.
  Scratch conflict detection includes overlapping buffers, not only pointer identity.
- TAR callers now use `reader(archive)` and `next(&reader)` and inspect
  `.status` before using `.entry`. Repository callers are migrated.
- DNS adds `query_ipv6`, `parse_ipv6`, and `resolve_ipv6` for AAAA records. Both
  resolver variants use one timeout budget across UDP and TCP, nonblocking socket
  operations, and caller packet capacity. The DNS server address remains IPv4.
  Negative timeout means no deadline. The resolver is a bounded stub resolver;
  it does not perform iterative resolution, DNSSEC, caching, or further CNAME queries.
- `net.socket_error` reads SO_ERROR for completion of nonblocking connects.

## Memory module consolidation

All arena, scratch, pool and free-list interfaces are in `std/mem`.
Removed `std/mem/owned`, `std/mem/growing`, and both `take` helpers.

| Previous | Current |
| --- | --- |
| `owned.Arena` | `mem.Arena` (no `.buffer` wrapper) |
| `owned.create(n)` | `mem.arena_create(n)` |
| `&result.arena.buffer` | `&result.arena` |
| `owned.release(&owner)` | `mem.arena_release(&arena)` |
| `growing.Arena` | `mem.GrowingArena` |
| `growing.create/try_push/push/reset/release` | `mem.growing_create/try_push/push/reset/release` (each function has the `growing_` prefix) |

`arena_create` returns `ArenaResult`: `.error` is a domain `ErrorKind`; `.code`
contains the native error. `arena_release` returns `Status` with native `.error`.
Buffer-backed arenas use the same allocation functions; release clears their
cursor without freeing the caller buffer. Fixed arenas do not silently grow.

OS `page_allocate`/`page_release` and their `try_` variants are removed from the
public platform modules. Mapping operations now exist only as private arena
backing implementations. Repository projects, benchmarks and platform probes
allocate through arenas. Pool/free-list helpers and byte operations are retained.

## SDK expansion

See [SDK additions](sdk-additions.md) for processes, filesystem watching, Unicode
text operations, property shrinking and temporary-directory cleanup. DNS address
owners must now match the queried name or its validated, bounded CNAME chain;
unrelated records are ignored, ambiguous/cyclic chains rejected.

Storage hardening: Unicode transforms, ZIP extraction/streaming, and XML namespace
entry now return `ErrorKind.Overlap` for rejected buffer aliasing. Process capture
rejects overlapping output/error buffers with `-22`. Allocate disjoint slices before
calling these interfaces. See `docs/sdk-additions.md` for partial-output and lifetime
contracts. Generic struct literals remain invalid syntax in compiler and editors;
local type aliases are explicitly unsupported (declare aliases at module scope).

## Preview memory and inspection additions

`mem.Arena` now carries peak/failure counters and an optional borrowed `observe.Log`
pointer/resource ID. Rebuild all modules and FFI mirrors together; do not reuse old
serialized descriptors. The event sink must live outside the observed arena.
`slot_map.lookup` adds a tagged Missing/Present result; existing `get` remains borrowed.
Frontend epoch 7 invalidates old semantic caches. New straight-line lifetime errors
can reject previously accepted local escapes and use after arena reset.
See [preview tools](preview-tools.md) for limits and commands.

## Earlier preview compatibility changes

When upgrading from older development snapshots:

- Rebuild Dyn objects, native libraries and FFI layout mirrors together. Aggregate
  arguments/results share target C ABI lowering across direct calls, indirect calls
  and callbacks. Do not reuse serialized arena or slot-map descriptors.
- Pool/free-list stride and backing alignment must be at least pointer-aligned,
  even when the requested payload alignment is smaller.
- Regenerate C bindings for target-sized aliases. Plain `std/c.char` follows target
  signedness; C `long` follows the target ABI, including Windows LLP64. Use explicit
  `(void)` for C functions with no parameters; non-prototype `()` declarations are
  omitted by binding generation.
- JSON nodes track their parent and reject duplicate attachment, cycles and
  reparenting. Use `#sizeof` rather than hard-coded `Value` layout sizes.
- Slot-map handles include backing identity. Handles from another store are
  rejected. Borrowed views still expire when their backing storage is invalidated;
  use `copy_into` with disjoint caller storage for retained bytes.

For current release artifacts, installation and publication, see
[distribution](release/distribution.md). For target and provider limits, see
[release readiness](release/readiness.md).
