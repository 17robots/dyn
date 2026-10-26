# Std contract corrections (2026-10-24)

This development migration removes caller-buffer producer forms and makes external-input diagnostics portable. It is not a compatibility guarantee for a published preview.

## Arena producers

Flags parsing is `flags.parse(&arena, options, arguments)`. Read `result.value.values` and `result.value.positionals`. Their arrays belong to the arena; argument strings remain borrowed. Failure rewinds this call's allocations. Regex compilation is `regex.compile(&arena, pattern)`; matching takes the resulting `Program` without caller workspaces. Program copies share mutable workspace, so concurrent matching requires separate compilations. Captures expire at the next operation on that program.

PNG/QOI encoding returns `result.value` bytes; decoding returns `result.value.info` and `result.value.pixels`. `inspect` returns an `InfoResult` with `value`. Fixed arena exhaustion panics; malformed external input returns failure and rewinds the arena. QOI validates its full pixel stream and end marker.

## Error fields

Migrated external-input results use portable `std/errors.Kind` in `kind`, the original native code in `error`, and a byte `offset` when meaningful. Pure parsers use native code `0`. Optional `detail` retains the former module-specific diagnostic; compare that field for precise parser cases. Tree parsers keep their payload name `root` and return their read-only stub on failure.

This applies to flags, regex, JSON, Metadesk, materialized INI, XML trees, URL, semver, PNG/QOI, DER/PEM and ZIP. PEM bytes moved from `data` to `value`. Zstd retains its unsigned provider diagnostic separately in `provider_code`; it is not an errno. An unknown-size valid Zstd frame remains a successful size query, but the current arena decompressor reports `Unsupported` for that shape.

## Thread lifetime

`thread.spawn(&arena, stack, entry, context)` and `spawn_with_size(&arena, size, entry, context)` return a `SpawnResult` whose `value` is a stable `*Thread`. Keep the arena, borrowed stack and context alive until successful `join`. Do not reset the arena while a thread is active. `join` returns a structured result and releases an owned native stack; it does not reclaim the arena's thread node. A zero thread can be joined safely. Failed creation rewinds its arena allocation and preserves native errors.

## Stateful and lookup corrections

Buffered I/O, INI scanners and WebSocket connections retain their first failure and stop further I/O. INI no longer recovers after malformed lines. Zero SHA-256 contexts initialize lazily. `sort.search` returns the input length on every miss; it no longer returns an insertion position. Failed Metadesk parsing returns the shared stub and rewinds its allocations.

XML additionally provides `parse`, `child`, `at` and `next_sibling`. Nodes belong to the arena; names, text and raw attributes borrow source bytes. It implements the existing scanner's XML subset, without entity decoding, DTD expansion or namespace resolution. Streaming APIs retain their separate caller-buffer protocols.

Migration and qualification status remains in [std standardization](../internals/std-standardization.md). Raw OS/C bindings, fixed-size primitives and streaming transfer protocols retain their documented exceptions; these do not exempt ordinary variable-size producers.

## Later closure corrections

`rand.State{}` now starts the same deterministic sequence as `rand.seeded(0)`.
Terminal operations and filesystem-capability reads return portable categories
alongside native errors. `terminal.restore` now returns a structured result;
filesystem-capability reads use `value`, `ok`, `kind` and `error` rather than an
enum payload.

Watcher events retain `event` and protocol `status`, add `kind` and `ok`, and
latch terminal failures in the watcher. `Empty` and rescan events do not become
terminal errors. A live watcher remains a single owner that must be closed.

DNS parsing and resolution now take an arena first and return complete address
slices in `Ipv4Result.value` or `Ipv6Result.value`. Resolvers own protocol-sized
packet storage. Parser failures return empty slices without consuming arena
storage, with an offset for malformed records.

`process.capture(&arena, path, arguments, configuration, policy)` grows both
captured streams in the arena. `CaptureOptions{}` has no output limit and an
infinite timeout. Set `timeout_milliseconds`, `output_limit` or `error_limit` for
explicit bounds. Timeout and limit failures retain partial output and reap the
direct child; other failures return no output and rewind capture allocations.
Arena exhaustion panics after deferred child cleanup.

AEAD seal/open and AES-GCM wrappers take the arena first. Seal results contain
`value.ciphertext` and `value.tag`; open results contain authenticated bytes in
`value`. Authentication failures clear unpublished plaintext before rewinding.
Fixed-size exchange/signature destinations remain caller buffers, with borrowed
success slices in `value`. Unsigned OpenSSL diagnostics remain `provider_code`,
not a fabricated native errno.

TLS results now belong to std and use portable `kind`, zero native `error`, and
provider-specific `detail`, `provider_code` and operation `provider_status`.
Retry conditions retain WantRead/WantWrite in `detail` and use `WouldBlock`.
ALPN configuration and shutdown return structured results. Certificate subject
text is formatted completely by the provider and copied into the arena; callers
read `certificate_subject(&arena, certificate).value` after checking `ok`.

HTTP results use portable `kind`, native `error`, and former module categories in
`detail`; parser results add `offset`. `http.close` and `http.route` return
structured results. WebSocket control operations return structured results too;
protocol event classification is now `event.detail`, leaving `kind` for portable
errors. Local validation failures have native code zero. HTTP servers, responses
and streaming bodies retain their first failure and suppress later I/O.

HTTP worker startup takes the arena first for stable thread nodes. Keep the arena,
workers, receive buffers, stacks and shared handler context alive until every
worker is joined. Zero workers own no active socket, including descriptor zero.

Complete HTTP exchanges are now `client_do(&arena, reader, writer, method,
target, host, body)` and `client_do_connection(&arena, connection, ...)`.
`decode_chunked(&arena, input)` returns decoded bytes in `value`, alongside
`consumed` and `count`. Failed exchanges rewind their allocations. These APIs
no longer use caller output buffers; fixed arena exhaustion panics. Streaming
servers still borrow their explicitly bounded receive storage. WebSocket
connections retain unread frames when a transport read coalesces several frames.

Clock reads now have one public path: `monotonic_now()` and `realtime_now()`
return `ClockResult`. `sleep()` returns `SleepResult`; the duplicate `try_*`
clock names and `sleep_result` are removed. Deadline construction and queries
return structured results too. Check `ok` before reading `value`. OS clock
failures propagate through polling, DNS and finite process capture instead of
panicking. Profiling completion and benchmark queries return structured results
and retain their first clock failure; benchmark queries take a mutable slot.

Text/HTML template parsing panics on arena exhaustion. CSV, XML and TAR stream
results retain portable I/O categories, including failures with native code
zero. Their precise module diagnostics use `detail`; scanner state may retain a
documented module-detail `error` alongside native `system_error`. TAR streaming
entry `typeflag` is the protocol byte; `kind` is the portable error category.
