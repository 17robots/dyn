# Changelog

Upgrade notes for Dyn code and the agents that write it. Newest release first.
Previews 9 to 11 are backward compatible: code that built on preview 8 still
builds. The one tooling exception is `dyn fmt --check`, which applies stricter
layout rules from preview 9 on. The other migrations below are cleanups, not
required fixes.

## Upgrading

Pin the new version and its checksums from [`mise.example.toml`](mise.example.toml),
run `mise install`, and confirm with `dyn version`. Restart editor language
servers so they pick up the new `dyn`.

## Unreleased

Breaking: see [docs/migrations/0.1.0-preview.40.md](docs/migrations/0.1.0-preview.40.md),
and run `dyn fix` first.

Language (2026-11-16 cleanup; see `docs/guide/rules.md`):

- A `for` with no condition and no `break` leaves only by `return` or a
  panic, so a non-void function may end with one; the `return` or `#panic`
  people wrote after it is no longer needed (and still allowed).

- Loops have no labels: `name: for`, `break: name` and `continue: name` are
  errors. Set a flag and break again, or move the inner loop into a function.
- `for *const value` is gone: `for *value` over a const slice already binds a
  `*const` pointer.
- `#offset` is gone: index a pointer range with `#slice(pointer, count)[i]`.
- An integer or text `case` always needs a `_` arm; covering every value with
  ranges no longer counts as exhaustive.
- A panic, or a failed run-time check, no longer runs defers. It runs the
  `panic.set_handler` handler, prints the message and trace, and exits with
  status 101. Move cleanup that must happen at a crash, such as restoring a
  terminal, into the handler.
- Arithmetic is target-typed: `total: u64 = a_u32 * b_u32` multiplies in
  `u64`. Write the narrow type where wrapping is meant
  (`hashed: u32 = value * 2654435761`).
- Signed and unsigned integers compare by value: `-1 < len` is true for a
  `usize` len, and `i64` against `u64` needs no cast.
- An unsigned `x % M` with a constant `M` narrows without `#cast`.
- `--check-overflow` checks every module, std and vendor included. Write
  `#wrapping(expr)` where arithmetic means to wrap (hashes, rotations, SWAR);
  std's own wrapping code is marked this way and runs clean with checks on.
- `for i in #step(first..last, n)` visits every n-th value;
  `#reverse(#step(...))` goes from the last.
- A generic `$T` bound to `u32` by one argument and `u64` by another is `u64`.
- A generic function used where a function type is expected takes its types
  from it: `hash: fn(u64, u32) u64 = key_hash`, or `key_hash` passed to such a
  parameter. `#instance(f, T)` remains only for functions whose `T: type`
  parameters the signature does not show.

Standard library:

- Failure is state you pass in: new `std/fail` (`fail.Status`, `fail.Failure`,
  `fail.Kind`, `fail.make`, `fail.set`, `fail.invalid`, `fail.describe`,
  `fail.panic_on_failure`). A function that can fail takes a `*fail.Status`;
  the first failure stays there with its kind, native code, operation, path
  and reason, and every later call given that status does nothing and returns
  zero or empty. Check `status.failed` once, before acting on the results.
  `Status.on_failure` is called once when the first failure is recorded.
  A `fail.Failure` keeps its own copy of its text (up to 228 bytes; a long
  path keeps its end), so it stays readable after the text it came from is
  gone; read it with `fail.operation_text`, `fail.path_text` and
  `fail.message_text`. `io.Kind` is now the same type as `fail.Kind`.
- `std/fs` moves to it. Every fallible function takes the status first (after
  the arena when it allocates): `fs.open(&status, path)`,
  `fs.read(&status, &file, buffer)`, `fs.write(&status, &file, bytes)` (no
  return), `fs.read_all(arena, &status, path, maximum)`,
  `fs.write_all(&status, path, bytes)`, `fs.metadata(&status, path)`,
  `fs.remove`, `fs.rename`, `fs.make_directory`, directory listing,
  `fs.copy_file`, the atomic-file functions, `fs.remove_tree`, `fs.lock`,
  `fs.truncate`, `fs.read_link` and `fs.app_directory`. `fs.File` loses
  `failed` and `failure` and gains `path`; `fs.Metadata`,
  `fs.DirectoryEntry` and the directory functions no longer carry failures;
  `fs.Result`, `fs.Mapping`, `fs.DirectoryResult`, `fs.PathResult` and
  `fs.AtomicResult` are gone. `fs.map` returns the bytes and `fs.unmap`,
  `fs.close` and `fs.atomic_abort` take no status, so cleanup works after a
  failure. Failures carry the system's own reason: "open app.json: no such
  file or directory", "read /tmp: is a directory".
- `std/io` streams move to it. `io.Reader` and `io.Writer` functions take the
  status: `read: fn(rawptr, *fail.Status, []u8) usize` returns the count, 0
  at the end of the stream. `io.read(&status, reader, buffer)` returns the
  count; `io.write(&status, writer, bytes)` writes everything (`write_all` is
  gone); `io.read_exact` fills its buffer or returns 0 at a clean end, and a
  stream that ends partway fails; `io.copy`, `io.copy_n`, `io.print_to`,
  `io.println_to`, `io.print_arguments` and `io.println_arguments` take the
  status. `bufio` follows (`bufio.read_line(&status, &reader, line)`,
  `bufio.writer_flush(&status, &writer)`; `ReadResult` loses `failure`), as
  do `json.write(&status, writer, value)` and `log.write(&status, &logger,
  ...)`. `io.Transfer` remains only for modules not moved yet, with
  `io.read_transfer`, `io.write_transfer`, `io.read_exact_transfer` and
  `io.from_transfer` to bridge them.
- Networking moves to it. `std/net`: every fallible call takes the status
  and returns its value: `net.socket(&status, ...)` (a descriptor),
  `net.tcp_listen_ipv4(&status, &address, backlog)` (a `Listener`),
  `net.tcp_connect_ipv4` (a `Connection`), `net.listener_accept`,
  `net.connection_read`/`connection_write` (counts; 0 is the end),
  `net.send`/`receive`/`send_to`/`receive_from`, `net.poll`/`net.wait` (the
  number ready, or the events), and the option setters (no return).
  `net.Result`, `ConnectionResult` and `ListenerResult` are gone. Nonblocking
  sockets use `net.try_send`, `net.try_receive` and `net.try_accept_address`,
  which report a socket that is not ready as `blocked`, not as a failure;
  `net.would_block(&status.failure)` tells such failures apart elsewhere.
  `std/event` (`event.open(arena, &status, n)`, `event.add/modify/remove(&status,
  &queue, ...)`, `event.wait(arena, &status, &queue, timeout)`,
  `event.waker_open(&status)`), `std/net/tls` (`Want` reports what a
  nonblocking connection waits for), `std/net/dns`, `std/net/url` and
  `std/net/websocket` follow.
- `std/net/http`: a `Handler` is `fn(*fail.Status, *Response, *const
  Request)` and returns nothing; `http.respond(&status, response, body,
  options)`, `respond_buffered`, `respond_stream` (returns the `Body`),
  `body_finish`, `http.add(&status, &router, ...)`, `serve_routes` and the
  replies (`http.text(&status, response, code, body)`) take the status. A
  failed write finishes the response or body: later writes fail with
  `InvalidState` instead of sending a broken message. `http.receive(&status,
  &server)` returns `Received{ request, response, ended }`; a clean end
  between requests is `ended`, not a failure. Parsers (`parse_request`,
  `parse_response`, `header`, `parse_url`, `parse_date`, `decode_chunked`,
  `chunk_step`, `form_decode`, `set_cookie`, `sse_event`, `multipart`) take
  the status and fail with `InvalidInput` at the offset where the input went
  wrong. `http.Result`, `ErrorKind`, `ReceiveResult`, `BodyResult`,
  `TextResult` and `DateValue` are gone. `std/net/http/evented` follows:
  `evented.start(arena, &status, ...)` returns the workers started,
  `evented.join(&status, workers)`, `run`, `later`, `receive_body`,
  `open_stream` and `upgrade` take the status, and finish functions take it
  first. The evented server is about 4% faster on small responses.
- `std/time`: reading a clock does not fail on the supported systems, so
  `time.monotonic_now()` and `realtime_now()` return an `Instant` (zero
  where there is no clock), `time.sleep` returns nothing, `time.elapsed`
  returns nanoseconds (saturating past ±292 years), and deadlines return
  their values. `time.checked_add/checked_sub` take a status.
  `ClockResult`, `SleepResult`, `DurationResult`, `DeadlineResult` and
  `ExpiredResult` are gone. `std/time/zone` takes the status
  (`zone.load(arena, &status, name)`).
- `std/process`, `std/process/signal`, `std/thread`, `std/thread/pool`,
  `std/sync` and `std/os/linux` take the status: `process.spawn(arena,
  &status, ...)` (a `*Child`), `process.wait(&status, child, false)` (an
  `Exit`), `process.environment(arena, &status, name)` (a `Variable`;
  `process.environment_or` needs none), `process.capture`,
  `process.arguments(arena, &status)`, `thread.spawn(arena, &status, ...)`,
  `thread.join(&status, thread)`, `pool.start(arena, &status, ...)`,
  `signal.watch(&status, set)`, `signal.wait(&status, &watch)` (a `Kind`),
  `sync.condition_wait_timeout(&status, ...)` (a `sync.Wait`).
  `thread.yield_now()` returns nothing. `bytes/builder` drops its sticky
  `failure`: `builder.append(&status, &b, bytes)`, and
  `builder.append_grow(arena, &b, bytes)`/`reserve(arena, &b, n)` take the
  arena first and panic like any arena push. `profile.finish` and the
  testing benchmark no longer report clock failures.
- New in `std/fs`: `fs.list(arena, &status, path)` (a directory's entries,
  copied), `fs.is_directory`, `fs.is_file`, and
  `fs.make_directory_exclusive`. `fs.make_directory` now succeeds when the
  directory exists.
- `testing.remove_temporary` takes a status.
- Decoders, parsers and codecs move to it, and `parse.Result` is gone. Each
  takes the status (after the arena when it allocates) and returns its value:
  `json`, `json/read`, `csv`, `xml`, `toml`, `ini`, `mdesk`, `msgpack`, `cbor`,
  `protobuf`, `base32`, `base64`, `hex`, `math/big.parse`, `regex.compile`, `text/template` and
  `html/template` (`render_with` callbacks take the status), `unicode`
  (`case_fold`, `normalize`, `word_breaks`, `line_breaks`,
  `next_grapheme(&status, &g)` returning a `Grapheme{ value, found }`),
  `text/layout`, `font` (`open`, `raster`, `atlas`), `audio/wav`, the image
  codecs (`bmp`, `tga`, `pnm`, `gif`, `jpeg`, `png`, `qoi`; `png.inspect`
  and `qoi.inspect` return an `Info`), `compress/zstd`, `archive/zip`,
  `archive/tar`, `crypto/der` (`der.next(&status, &cursor)`), `pem`,
  `certificate`, `x509.inspect`, `aead.seal/open`, `aes`, `signature`,
  `exchange`, `hpack`, `qpack`, `fs/watch` and `ui/software.render`.
  Malformed input fails with `InvalidInput` and the byte offset
  (`failure.offset` when `has_offset`); `fail.at(&status, kind, op, msg,
  offset)` records one. Iterators return `Next{ value, offset, found }`.
  Readers that failed (zip and tar streams, watchers, der cursors) replay
  the same failure. `x509.validate` returns a `Validation` with `valid` and
  `reason`, not a failure. Authentication failures are `InvalidInput`
  "authentication failed". The `std/encoding` module (its shared `Result`)
  is gone.
- Vendor packages move to it. `vendor/sqlite`: `open`, `prepare`, `step`,
  `reset`, the binds, `column`, `execute`, `begin`/`commit`/`rollback`,
  `run`, `first`, `query`, `next`, `cached`, `open_schema` and `transaction`
  take the status; `finalize` and `cache_close` take none.
  `sqlite.constraint(&status.failure)` replaces `constraint(statement)`,
  `StepResult` is gone (`step` returns the `State`), and a failure keeps
  SQLite's code in `failure.native`. The window, OpenGL, Vulkan, SDL3,
  FreeType, HarfBuzz, FriBidi, `vendor/text/layout`, miniaudio, zstd, lz4,
  pcre2, lua, libarchive, curl, tree-sitter, cgltf, stb, enet and box2d
  bindings follow; library loaders (`opengl.load`, `freetype.load`, ...)
  return their `Api` and fail with `NotFound` naming the missing symbol.
- The old failure types are gone: `io.Failure`, `io.Result`, `io.Bytes`,
  `io.Count`, `io.Transfer`, `io.Status`, `io.complete`, `io.failed`,
  `io.failure_if`, `io.describe`, `io.kind_text`, the `io.*_failure`
  constructors, the `io.Kind` alias and the bridges `io.read_transfer`,
  `io.write_transfer`, `io.read_exact_transfer` and `io.from_transfer`. Use
  `fail.Kind`, `fail.describe`, `io.read`, `io.write` and `io.read_exact`;
  `io.print` writes without a status. `io.linux(code)` and the other code
  tables return a `fail.Kind`. `std/text/edit` takes the status
  (`edit.validate(&status, &context)`, `edit.snapshot(&status, &tracker,
  ...)` returns the `Context`, `edit.apply(scratch, &status, &buffer,
  &replacement)`), as do `events.collect_edit(&status, &collector, &event)`
  and the OpenSSL AEAD and key helpers (which return the bytes written).
- One shape everywhere: a call that can fail takes `&status`, a result that
  can come up empty has `found`, and you check `status.failed` before using
  what you got (see "Errors and cleanup" in `docs/guide/idiomatic-dyn.md`).
  The last exceptions move to it:
  - Vendor calls that reported failure as `bool`, a code or a bare `nil`
    take the status: SDL3 (`init_video`, `gl_*`, `clear`, `present`,
    `texture_draw`, audio streams, GPU, ttf, mixer), microui, box2d, cgltf,
    enet, lua (`create_owned`, `pop`), curl `init`, stb `resize`, miniaudio
    sound controls and `play_file`, tree-sitter (`parser_create_owned`,
    `parser_language`, `tree_copy_owned`, `tree_edit`). Destroy functions take
    none. `sdl3.window_pixel_size` returns a `PixelSize`;
    `cgltf.world_transform` and `base_color` return arrays; cgltf's optional
    indices return `Index{ value, found }` instead of -1.
  - Crypto primitives take the status: `chacha20`, `poly1305` (tags are
    `[16]u8`), the AES-GCM and ChaCha20-Poly1305 primitives, HKDF, PBKDF2,
    Argon2id (`argon2id_verify` and `argon2id_decode` too), the Ed25519,
    P-256 and X25519 key and signing functions and `random.fill`. Hash
    `update` functions return nothing.
  - `fmt.buffer(&status, storage)`, `html.writer(&status, storage)` and
    `json.writer(&status, storage)` record into the status instead of their
    own `failed` flag; `html.failed` and `json.failed` are gone.
    `http.page_writer(&rendering, response, storage)` takes a status of its
    own so `http.page` can still answer 500.
  - Bad input that came back as `valid = false` fails on the status:
    `time.parse_iso8601`, `path.safe_join`, `path.relative`, `big.to_u64`,
    `big.divide`, `big.power_mod`, `search.prepare`, `testing.summarize`.
    `path.join` and `path.clean` return the bytes. `utf8.next` has `found` and
    gives U+FFFD for an invalid byte; `utf8`/`utf16` `codepoint_count` return
    a count. `flags.Value.present`, `http.ByteRange.present` and pcre2's
    `Span.set` are `found`. png and qoi `Info` lose `valid`.
  - Matrix and quaternion functions return plain values (`Mat3`, `Mat4`,
    `Quat`, `Vec3`); degenerate input gives the zero value, and the
    `*Result` types are gone.
  - `parse.malformed` and `parse.failed_at` become `fail.at(&status, kind,
    operation, message, offset)`.
  - `vendor/openssl/tls` takes the status and returns a `Want` when the
    socket is not ready; its `ErrorKind` and result types are gone.
    `tls.server_alpn` and `evented/tls.offer_http2` take the status.
    `quic_read` and `quic_write` take the status too and return a
    `QuicAttempt` (`count`, `blocked`, `ended`); a stream the peer resets
    fails with `Interrupted`. `QuicStatus` and `QuicIo` leave the vendor
    module, and `evented.QuicStatus` loses `Reset`.
  - `observe.record` and `progress` `advance`/`end` return nothing (drops
    are counted). `bytes.Builder` is removed; use `std/bytes/builder`.
  - Fixed: cgltf reported a missing file as out of memory.
- HTTP:
  - A handler that fails before responding gets `500 internal server error`
    from the server (evented over HTTP/1.1, HTTP/2 and HTTP/3, and
    `serve_stream`), and the failure is logged to `Config.access_log`. So a
    handler passes its status to every call and never answers its own
    failures.
  - Responding twice fails with `InvalidState` "already responded".
  - `Config.on_too_large` and `Config.on_busy` replace the server's own 413
    and 503 replies with your handlers.
  - `http.query_has(request, name)`.
  - `ResponseOptions.cookies` takes `http.Cookie` values and writes the
    `Set-Cookie` headers itself. `http.redirect(status, response, location,
    cookies)` takes cookies instead of formatted text, and `sessions.start`
    and `sessions.forget` return an `http.Cookie`.
  - `http.page_writer(&status, response, storage)` takes the handler's status
    again: a page that does not fit fails it, and the server answers 500.
- Std has three layers, listed in `std/layers.txt` and shown in the std
  index: core (no operating system, no memory source), heap (arenas and what
  builds on them) and std (needs an operating system). Core and heap build
  for every target; the suite and CI check all 110 of those modules on
  riscv64-none, riscv32-none and thumbv7em-none, and that no module imports
  a higher layer.
- Counts, lengths and indexes are `usize` across the vendor wrappers too:
  `sqlite` column and parameter indexes and `column_count`
  (`Statement.columns`), `pcre2.capture`, `tree_sitter` `child`,
  `child_count`, `node_start` and `node_end`, `lua.pop` and `stack_size`,
  `stb` image and atlas sizes, and `font.raster`'s `pixels_per_em`. The
  rule is in `docs/guide/style.md`.
- Arenas (`std/mem`) keep a small core. Running out always panics, a fixed
  buffer included, with a message that says whether the buffer was full, a
  limit was reached or the source had no more memory:
  - Create with `arena_alloc(block_size)`, `arena_from_buffer(storage)` or
    `arena_from_source(source)`. A `mem.Source` says where blocks come from
    and caps them: `mem.pages(limit)` for OS pages, `mem.within(parent,
    limit)` for blocks pushed onto another arena, or your own `take` and
    `give` (16-byte aligned blocks).
  - Push with `push(T, arena)`, `push_array(T, arena, count)` (both zeroed)
    and `push_bytes(arena, count)` (uninitialized, unaligned; it was
    `push_bytes_uninit`).
  - Take back with `arena_mark`/`arena_rewind`, `arena_reset` and
    `arena_release`; measure with `arena_used`. `arena_room` is the largest
    push that cannot run out; std producers that guess an output size cap
    the guess with it, so output that fits a small buffer arena still lands
    there.
  - Removed, with what to use instead:
    - `try_push`, `try_push_array`, `arena_try_push*`, `arena_try_alloc*`,
      `ErrorKind` and `Allocation`: the plain push; size the arena for the
      work.
    - `arena_push`, `arena_push_uninit`, `arena_push_array`: `push(T)`,
      `push_array(T, n)` or `push_bytes(n)`.
    - `arena_alloc_bounded(block, limit)`: `arena_from_source(source)` with
      `source := mem.pages(limit)` and `source.block_size = block`.
    - `arena_sub(parent, size)`: `arena_from_source(mem.within(parent,
      size))`.
    - `arena_snapshot`, `arena_capacity`, `arena_start`, `peak_used`,
      `allocation_failures`: `arena_used`; an arena's first position is
      `mem.ArenaHeader`. `arena_remaining` becomes `arena_room`, which also
      counts what a limit still allows.
    - `append`, `append_many`, `append_grow`, `append_many_grow`,
      `try_append`, `arena_try_extend`: `std/container/array` or
      `std/bytes/builder`, which double when full (a builder that is the
      arena's newest push grows in place).
    - `scratch_begin`/`scratch_end` and `Frames`: a mark and a rewind on a
      second arena; two arenas swapped each frame.
    - `trial_size`/`trial_next`, `size_for`: gone; `push_array` checks its
      size.
    - `arena.events`: `std/observe` logs stay for file capabilities and your
      own events.
  - `fs.read_all` no longer fails with `Capacity`: an arena that cannot hold
    the file panics.

Compiler:

- Fixed: on x86-64 release builds, a call in a function the program never
  reaches could stop a constant argument from being folded into a function
  it does reach, so importing an unused module could change the code of
  used ones.

Compiler speed of generated code:

- Struct and array parameters are copied less. An inlined body reads a
  caller's local in place when it never writes the parameter or takes its
  address; a callee keeps a stack-passed struct where it arrived and reads a
  by-pointer one (AArch64, Windows) through the pointer, outside debug
  builds; a caller passes a local whose address is never taken without a
  snapshot. A 64-byte struct passed by value to an inlined function costs no
  copy (0.046 to 0.030 s on `tools/bench/bodies`), and an out-of-line call
  one copy instead of three.
- `tools/bench/run.py` also builds each kernel with Zig (ReleaseFast and
  ReleaseSafe); see PERFORMANCE.md.

Tools:

- `tools/bind-vendors.py` builds the raw OpenSSL binding against OpenSSL 4
  as well as 3: removed ENGINE calls bind to OpenSSL's own stubs, and a
  macro helper gives way when the header declares the real function
  (`BIO_eof`).
- Errors can carry a fix. Text output prints it under the snippet
  (`fix: replace 'push_bytes_uninit' with 'push_bytes'`), and
  `--diagnostics json` adds `"fix": {replacement, path, certain, offset,
  length, range}`. A certain fix keeps the program's meaning; a
  `suggestion:` (the closest name to a misspelled one) does not promise to.
- `dyn lsp` offers the same fixes as quick fixes (`data.fix` on each
  diagnostic); certain ones are preferred.
- `dyn fix DIR` applies every certain fix to the module's own files, repeats
  until none is left, and then checks. It is the migration tool between
  releases: removed std and vendor functions name their replacement, and
  same-argument renames are fixed.
- Errors for habits from other languages say what to write instead and fix
  what is mechanical: `let x = 1`/`var`/`let mut` to `x := 1`, `while` to
  `for`, `x++` to `x += 1`, `for *const` to `for *`, an array passed where a
  slice goes to `values[..]`, string `+`, `? :`. A wrong argument count shows
  the signature: `strings.clone takes 2 arguments (arena: *Arena, source:
  []const u8), got 1`. Names other languages use for std functions
  (`fs.list_dir`, `fs.create_dir_all`, `fs.exists`, `strings.equal`, ...)
  say what Dyn calls them, and a member with no close spelling lists related
  ones (`related: fs.list`).
- Two neighboring arguments that each fit the other's parameter are reported
  as swapped, with the swap as a suggestion: `function arguments 1 and 2 look
  swapped (expected *Arena, *Status; found *Status, *Arena)`.
- `dyn guide` prints the guide built into the compiler: `--brief` for one
  page of what to write (and what not to bring from Go, Rust, Zig or C), or a
  topic: `rules`, `idioms`, `language`, `memory`, `collections`, `std`,
  `style`, `agent`.
- `tools/agent-eval` measures how well an agent writes Dyn: seven specified
  tools with graders, and a harness that counts first-try checks and repair
  rounds for any agent command.
- `dyn check` and `dyn vet` check std and vendor function bodies only when
  the program can reach them; `dyn check` on a library module still checks
  all of it. Checking the compile-budget fixture makes 16% fewer
  allocations and peaks at 31 MiB instead of 42.
- `dyn vet` warns about a struct local declared without a value that is only
  ever passed by pointer and never read, such as a `fail.Status` nothing
  checks (`_ = status` drops it on purpose), and about a result tested for
  being empty before the status its call filled in is read. Both go by shape;
  no type is known by name.
- `panic.assert(condition, message)` checks a condition in every build.
- Image `width` and `height` (`image.View`, every encoder) and font sizes
  (`font.Bitmap`, `font.Atlas`, `font.AtlasGlyph`, `font.atlas`) are `usize`.
- Stack traces and runtime check failures name functions without the module
  prefix.

Servers:

- One server and one router. `std/net/http/concurrent` (the blocking worker
  pool) is gone: use `std/net/http/evented`, which on four workers ran
  738k keep-alive requests a second from 32 clients where `concurrent` ran
  478k. The
  exact-path `http.Router` (`router`, `route`, `dispatch`, `Route`) is gone:
  use `http.Routes(T)` (`typed_routes`, `add`, `bind_routes`), which also
  has `:name` segments and 405 with `Allow`.
- `http.serve_stream` takes the context argument that `serve_stream_context`
  took; `serve_stream_context`, `serve_connection`,
  `serve_connection_context` and `connection_server` are gone. Wrap a
  connection with `net.connection_reader` and `net.connection_writer`, and
  build a `Server` with `http.server`.
- Gone with them: `http.accept`, `http.close` and the `http.Listener`,
  `http.Connection`, `http.StreamReader`, `http.StreamWriter`,
  `http.StreamResult` and `http.AcceptResult` aliases. Use the `std/net` and
  `std/io` names.
- `evented.serve` works on macOS and Windows: without load-balancing
  `SO_REUSEPORT` it shares one listener across workers. It failed with
  Unsupported there before.
- Linux sockets are close-on-exec, like files, so a spawned program no longer
  inherits listeners and connections. `net.accept_address` takes a
  `nonblocking` flag and sets it in the same call (`accept4` on Linux).
- Routes without `:name` segments no longer copy the request: dispatch over
  11 routes takes 7 to 38 ns, down from 15 to 41.
- HTTP/3 is marked experimental in the guide.

- `html.print` escapes every value that is not text or `Trusted` after
  formatting it. A struct whose field held `<script>` was written raw.

- `sqlite.open_schema` waits for other connections' writes with
  `sqlite.busy_wait`, which retries from 20 microseconds up to 1 millisecond
  apart, instead of SQLite's busy timeout, which sleeps whole milliseconds.
  Hold one app mutex around writes for full speed (docs/guide/web-apps.md).
- `Config.slow_handler_microseconds` warns about handlers that run that
  long (blocking work on the event loop), in the access log or on stderr.
- `std/cache`: per-worker copies of shared data, from the pattern the
  session cache used. `std/net/http/session` now builds on it.
- `evented.job` panics, naming the type and both sizes, when the job type is
  larger than `Config.job_size`. It used to return nil on every request.

Finding things:

- A misspelled module member suggests the closest public name
  (`'strings' has no pub member 'formatt'; did you mean 'strings.format'?`),
  and a private one says it is not pub.
- `import io` and `[3]i32{1, 2, 3}` get errors that show the Dyn spelling.
- [docs/guide/std-index.md](docs/guide/std-index.md) lists every public std
  declaration, generated by `tools/std-index.py`; a test keeps it current.
- `tests/release-parity.py` builds every runnable test and example in debug
  and release and compares what they print.
- `tools/fuzz-parity.py` builds random well-typed programs in debug,
  release, O3 and on the tree code generator and compares them (300 agree);
  `tools/bisect-passes.py` names the optimization pass behind a release
  build that differs, through `DYN_SKIP=<pass>`.

Fewer hidden compiler rules:

- Integer arithmetic wraps in debug builds too. `--check-overflow` opts in
  to overflow panics, now in debug and release builds alike.
  `--no-check-overflow` is still accepted and is now the default.
- The SDK's std and vendor code is recognized by its location in the SDK,
  not by a path that contains `/std/` or `/vendor/`. A project under such a
  directory is no longer exempt from `--check-overflow`, vet and the copy
  warnings.
- `&T{...}` takes the address of a struct literal; the storage lives until
  the end of its block. `&f()` stays an error with a clearer message.
- Storing a local's address through a parameter or into a global is an
  error, like returning it.
- `x & M` with a constant `M`, and an unsigned `x >> k` with a constant `k`,
  convert to a smaller integer type without `#cast` when the result fits:
  `low: u8 = word & 0xff`, `top: u8 = x >> 56`.
  `dyn vet` reports casts the rule makes unnecessary; 104 are gone from std,
  vendor and the examples.
- `#sqrt`, `#floor`, `#ceil`, `#trunc`, `#round` and `#fma` are builtins:
  one instruction where the target has it, compiler-provided software
  elsewhere. `std/math`'s `sqrt64`, `floor64` and the others call them. The
  compiler no longer recognizes those std functions by name.
- Names starting with `dyn_builtin_` or `DynBuiltin` are reserved for the
  compiler.
- Format templates are ordinary library code. The compiler no longer treats
  a parameter named `template` specially: it neither checks `{}` counts nor
  rewrites struct arguments. Structs and plain enums print at run time
  through their `TypeInfo` (`Unit{name: ada, at: Vec2{x: 1.5, y: 2}, op:
  Sub}`), from any expression; plain enums with set values print the
  variant's name. `dyn vet` reports a literal template whose `{}` count
  differs from its values; at run time a mismatch prints `{?}` or `{+value}`.
- The compiler knows no std function or type by name. Gone with that: the
  vet warnings for copying `Arena`, `File`, `Thread` and other std handles,
  and the errors for using arena memory after `arena_reset`. Returning or
  storing the address of a local is still an error. `poison_on_rewind`
  remains the run-time aid for stale arena memory.
- `process.spawn` returns `*Child`, kept in the arena it is given;
  `process.take` is gone.
- Handles are plain values: copy them freely, close them once. `fs.take`,
  `fs.borrow`, `fs.borrow_handle`, `net.listener_take`,
  `net.connection_take` and `File.owned` are gone; assign the handle
  (`file := opened.value`) instead. `dyn vet` warns about the obvious
  mistake, by shape: a variable copied with `=` and both copies passed to
  the same function, as in `fs.close(&file)` then `fs.close(&copy)`.
- `#typeof(value)` on an `any` gives the boxed value's `TypeInfo` at run
  time. `TypeInfo` ids are the same numbers an `any` carries: unique in a
  program (two modules' `Point` types no longer share one) but not stable
  across builds. `reflect.address` and `reflect.point` read and make `any`
  values; `fmt.write_value` writes one.
- `#init(p)` now makes `*p` a fresh value: zero, then field defaults, for
  every type. `mem.push` and `mem.try_push` take uninitialized memory and
  call it, so a pushed struct is filled with stores in place. Before,
  `#init` only wrote defaults and the compiler zeroed pushes by recognizing
  std/mem's `zero_bytes_fast` by name; that rule is gone.
- The compiler no longer replaces `bytes.find_byte`, `bytes.find` or the
  JSON string scanner with inline SSE by recognizing their names.
  `bytes.find_byte` calls an SSE2 routine in the x86-64 runtime
  (`dyn_find_byte`) through an ordinary `extern`, and reads eight bytes at
  a time on other targets. `bytes.find` builds on it. The JSON scanners
  share `std/encoding/json/scan`, which calls a second SSE2 routine
  (`dyn_json_text_prefix`) on x86-64; the JSON benchmark kernel runs within
  1 percent of the old inline SSE.
- `TypeInfo`, `TypeMember` and `TypeKind` are builtin type names, reserved in
  every module; declaring one reports that. Before, a declaration collided
  with `#typeof`'s types only in some programs.

Web applications: see [docs/guide/web-apps.md](docs/guide/web-apps.md).

- Shorter web apps, with no language change:
  - `json.object_of`/`json.array_of` write structs as JSON objects, by
    field name. `#typeof` field descriptors now carry each field's byte
    offset in `TypeMember.value`.
  - `html.print` fills `{}` with escaped text, numbers, or `Trusted` markup.
    `http.page_writer` and `http.page` send a page from the send buffer,
    with CSP and nosniff.
  - `std/net/http/session` gives tokens, CSRF secrets, the `sid` cookie and
    a per-worker cache in front of the app's own store.
  - `Config.access_log` logs each request. `log.write` writes a line in one
    write.
  - `sqlite.open_schema`, `sqlite.transaction`, `http.assets_of` and
    `process.environment_or` cover the rest. `http.Response.status` records
    the status sent.
  - Chirp went from 538 to 416 lines, as fast as before.
- `evented.later` finishes a request after the worker's current pass over
  ready connections, so handlers can group work, such as one transaction for
  many inserts. Chirp's post creation went from 85k to 198k per second.
- The evented server scans only the connection slots it has used, not all
  `connections_per_worker`: a published message used to walk every slot on
  every worker. HTTP header parsing finds line ends with `bytes.find_byte`
  and checks token bytes against two bit masks. Static responses are about
  10% faster, and a post with a live feed 22% faster in Chirp.
- The SSA backend combines byte loads and stores on x86-64 and AArch64:
  `x[0] | x[1] << 8 | ...` from consecutive addresses is one load, and
  storing a value's successive bytes (or constant bytes) one store.
  `binary.load_u64_le` and `store_u64_le` compile to one instruction each;
  BLAKE2b is 7% faster.
- `html.text`, JSON string writing and `utf8.valid` look at eight bytes at
  a time while nothing needs escaping or decoding: text without specials
  escapes twice as fast. Text with an entity every few bytes runs as before.
- `vendor/sqlite`: statements keep their column count, and `integer`,
  `bytes` and `text` read a column with one or two SQLite calls instead of
  four. `integer` converts the way SQLite does (text is parsed), and `bytes`
  returns a number's text.
- SHA-256 uses the CPU's SHA instructions on x86-64 when CPUID reports
  them (the runtime checks once and falls back to the Dyn code otherwise):
  about 7 times faster. HMAC-SHA256 hashes a message of up to 55 bytes in
  one block per pad. PBKDF2-SHA256 with 20,000 iterations takes 1.8 ms,
  against 7 ms before and OpenSSL's 2.2 ms on the same machine. The
  language is unchanged: the instructions live in the runtime assembly
  (`runtime/native_sha256_x86_64.S`), as `memcpy` does.
- Shorter servers. `vendor/sqlite` gains a per-connection statement cache
  (`cache`, `cached`, `cache_close`) and one-call forms: `run`, `first`,
  `query`/`next`, `integer`, `bytes`, `text` and `constraint`. `std/net/http`
  gains `http.text`, `http.json` and `http.redirect`; `std/encoding/json`
  gains `json.field`. The evented server gives each worker a request arena
  (`evented.arena`, `Config.request_arena_size`) and names the worker
  (`evented.worker_index`), so each worker can own a database connection
  without a lock, and `evented.serve` serves until SIGINT or SIGTERM. Chirp
  went from 750 to 422 lines (Go 435, Rust 393), with the same throughput
  on reads and 13% more on writes.
- Threads from `std/thread` and `std/thread/posix` start with SIGINT, SIGTERM
  and SIGHUP blocked. A pool started before `signal.watch` used to take the
  signal and end the process instead of letting it shut down.
- `dyn fmt` puts a guard on one line when it fits in 100 columns:
  `if done { return value }` for an `if` with no else whose block is one
  return, break or continue. `dyn fmt --check` reports code with these
  guards spread over three lines. std, runtime and vendor are reformatted,
  about 5,800 lines shorter.
- Fixed a release miscompile: the O2 inliner treated a leaf that reads a
  field through a pointer as pure, and could run it before an earlier
  argument's call. `f(run(p), code_of(p))` read `p.code` from before
  `run`. Debug builds and O1 were right.
- SSA folds: `(b + c) - b` is `c`, so `xs[b..b + 4]` has a constant length
  and its constant indexes need no checks; `(p << k) * q` becomes
  `(p * q) << k`, and on x86-64 `t + (p << k)` becomes one LEA, so
  `a + b + 2 * x * y` costs one multiply. Constants move to the right of
  commutative operations. Argon2id takes 11.4 ms (it took 13.4 ms; Go
  takes 11.1 and the reference C 10). Functions with loops start on 64-byte
  boundaries, so an unrelated edit no longer moves a hot loop's speed by
  a third. `tools/codegen-bench.py` measures kernel time, spills and stack
  traffic against a saved baseline.
- HTTP/2 in `std/net/http/evented` with `Config.http2`: TLS clients through
  ALPN (`https.offer_http2`) and prior-knowledge cleartext clients, on the
  same port as HTTP/1.1. Streams run the ordinary handler; run, open_stream
  and receive_body work per stream. Flow control both ways, fixed memory
  (`http2_connections`, `http2_slots`). `std/net/http/hpack` implements
  HPACK; `tls.server_alpn` selects ALPN on servers.
- The evented server's memory no longer swells under transparent huge
  pages: each worker's storage is one block marked with the new
  `mem.advise_sparse`, so a few busy connections touch 4 KiB pages, not
  2 MiB ones. Chirp went from 13 to 8 MiB idle and 22 to 11 MiB under load,
  level with Rust and C.
- x86-64 and AArch64 emit one rotate for 64-bit `x >> c | x << (64 - c)`,
  and x86-64 a 32-bit move for `x & 0xffffffff`. Argon2id is 2.4 times
  faster (32 to 13 ms for OWASP's 19 MiB setting; the SIMD reference C
  takes 10): its permutation keeps G's words in locals, uses fixed offsets
  and reuses two blocks of workspace (`argon2id_workspace_words` grew by
  two blocks).
- HTTP/3 in `std/net/http/evented` with `Config.http3` and a QUIC stack in
  `Config.quic` (`https.quic` over OpenSSL's QUIC server): UDP on the TCP
  port, Alt-Svc on TCP responses, and streams on the HTTP/2 machinery, so
  run, open_stream and receive_body work per stream. `std/net/http/qpack`
  implements QPACK without a dynamic table.
- WebSockets over HTTP/2 (RFC 8441): `evented.upgrade` on an extended
  CONNECT stream answers 200 and carries frames in DATA; send, publish,
  close_peer and on_message work as on HTTP/1.1.
- Request bodies of any size: `Config.on_large_body` gets requests whose
  body fits no buffer, and `evented.receive_body` hands it over piece by
  piece, chunked framing removed (`http.ChunkReader`), then calls finish
  with how it ended. Without it they still get 413.
- `evented.respond_compressed` gzips dynamic responses with a per-worker
  encoder (`Config.compress_level`) when the client accepts gzip, the type
  compresses and the body is at least 1 KiB; `http.respond_compressed`
  takes the encoder itself.
- A bare block, `{ ... }` as a statement, opens a scope: its locals end and
  its defers run at the closing brace. Hold a lock for part of a function
  without a helper function or `if true`.
- SHA-256 is about 15 times faster (25 to 380 MiB/s on x86-64), and PBKDF2
  about 26 times (20,000 iterations: 185 to 7 ms). `std/crypto/core` built
  32-bit arithmetic from 64-bit remainders and multiply loops; ChaCha20 and
  the WebSocket SHA-1 did too. `hmac.sha256_key` and `hmac.sha256_with`
  hash an HMAC key once for many messages.
- x86-64 and AArch64 release builds emit 32-bit operations for `u32`
  arithmetic whose result is truncated anyway, and a rotate for
  `x >> c | x << (32 - c)`, also on `u32` loop variables.
- The inliner expands every call to a small pure function in a statement,
  not only the first: `rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)` becomes
  straight-line code. A user-written SHA-256 runs 2.4 times faster.
- Assembly listings name `rol` and `ror`.
- Literal arithmetic such as `1 << 15` or `3 * 4` adapts to a generic call's
  parameter type like a plain literal, instead of defaulting to `i32`.
- `std/crypto/blake2b`, and Argon2id in `std/crypto/password`
  (`argon2id`, `argon2id_encode`, `argon2id_verify`), checked against
  RFC 9106 and the reference implementation.
- `std/compress/deflate` gains a real encoder (`deflate`): hash chains, lazy
  matching, zlib's level parameters and dynamic Huffman blocks, with output
  within 0.1% of zlib. `gzip.compress` and `gzip.write` use it.
- `json.writer` writes JSON into caller storage with automatic separators.
- `std/net/http`:
  - Breaking: 413 is reported as "Content Too Large" (RFC 9110); the
    constant keeps its name `StatusPayloadTooLarge`.
  - Breaking: every response carries `Date` unless
    `ResponseOptions.omit_date` is set.
  - Breaking: 1xx, 204 and 304 heads carry no `Content-Type` or
    `Content-Length`, and `respond` rejects a body for them. An empty
    response without a content type no longer sends one.
  - `GET` routes answer `HEAD`.
  - `status_reason` covers every registered code; more `Status*` constants.
  - New helpers: `cookie`, `cookie_in`, `set_cookie` (`Cookie`, `SameSite`),
    `format_date`, `parse_date`, `sse_event`.
  - Static assets: `make_asset`, `load_directory`, `find_asset`,
    `serve_asset` (with single byte ranges, 206 and 416), `byte_range`,
    `content_type`, `accepts_encoding`, `etag_matches`.
  - `multipart` and `next_part` for `multipart/form-data`.
  - `Limiter`, `allow` and `ip_key` for rate limits.
  - A small chunk of a streamed body is now sent as one write.
- `std/net/http/evented`:
  - `run` hands a request to a thread pool and answers it from a finish
    function; `job` gives per-connection job storage.
  - `open_stream` (Server-Sent Events, long polling) and `upgrade`
    (WebSocket) return a `Peer`; `send`, `publish` (topics) and `close_peer`
    reach peers from any thread; `Config.on_message` receives WebSocket
    messages.
  - When every slot is busy, an idle keep-alive connection is evicted, then
    `Config.overflow` decides: `Wait` (default) holds the client in a
    reserve slot, `Reject` answers 503. Before, new clients waited in the
    kernel backlog behind idle connections until those timed out.
  - `client_ip` gives the client's address.
  - Request bodies larger than `receive_size` borrow a block from an
    upload pool (`Config.upload_size`, `upload_count`); `Expect:
    100-continue` is answered.
  - Chunked request bodies are accepted and decoded in place, by both
    servers (`http.frame_request_decoding`); before, they got 400.
  - Breaking: `storage_size` grows for reserve slots, job storage and the
    inbox.
- `std/event` gains `Waker` for waking a queue from another thread.
- `std/thread/pool` gains `start_spawned` for pools on a custom spawner.
- `std/net` gains `address_ip` and `ip_text`.
- `vendor/sqlite` gains `bind_values` and `done`.

## 0.1.0-preview.39

Breaking: see [docs/migrations/0.1.0-preview.39.md](docs/migrations/0.1.0-preview.39.md).

- `examples/` is now a course: nine tested projects in order, from the Game
  of Life to a multi-threaded prime counter, each with a README of what it
  teaches and exercises. `examples/learn` moved to `examples/tour`.
  `tests/examples.py` replaces `tests/learn-example.py`: it formats, vets
  and replays every example's `session.txt` in debug and release.
- Breaking: `union` types are removed. `union` stays a reserved word, and a
  `union` declaration fails with "union types were removed; use #bitcast or a
  payload enum". Nothing in `std` or `vendor` used them.

  | Old | New |
  | --- | --- |
  | `union W { bits: u64, number: f64 }` then `w.bits` | `#bitcast(u64, number)` |
  | A union that stores one of several shapes | A payload enum |
  | A field that mirrors a C union | The largest member's size and alignment, such as `[4]u32` |

## 0.1.0-preview.38

- Release builds no longer hang on functions with many loads and no write
  between them, such as a text `case` with 25 or more arms or one long `||`
  over struct fields. The load-reuse table is now sized for every load in the
  function, so its probe always ends. Generated code is otherwise unchanged.
- A text `case` with more than four patterns dispatches like an integer case:
  on the length, then on the bytes that tell the patterns apart, and compares
  the rest of the one candidate left. A lookup no longer grows with the number
  of arms: 200 keywords run about 9x faster, 40 about 2.4x, 8 about 1.2x.
  Debug builds of a text case are about 3x smaller: an index the case has
  already proven in bounds keeps no bounds check. Which arm runs is unchanged.
- The tree emitter (`DYN_NO_SSA=1`) builds a text case in debug builds; a
  literal `if true` no longer looks like it can fall off the end of a function.
- The guide says text patterns are string literals; named constants are for
  integer and enum patterns.

## 0.1.0-preview.37

- A struct or enum from any expression now prints its contents in a literal
  format template: `io.println("{}", spot())` evaluates `spot()` once, before
  the call, with the call's other arguments, in order. Such a call must be its
  own statement; inside a condition, after `&&` or in a `defer` it is an error
  that says to bind the value to a name. Enums print from any expression.
- Native debug builds keep overflow checks and correct DWARF scopes: sibling
  `if`/`else` locals no longer both show in `info locals`.

## 0.1.0-preview.36

Breaking cleanup before the language freeze; see
[docs/migrations/standard-20261113.md](docs/migrations/standard-20261113.md)
and run `tools/migrate-standard.py`.

- One spelling each: `Type{...}` literals only (`.{...}` is gone), a declaration
  without an initializer is the one way to get zero (`= []` on a declaration is
  an error), integers become enums only through `enums.from_int`, and
  `#bitcast` takes numbers only.
- Comparisons no longer chain, and locals never shadow another name in scope.
- `for x, i in xs` binds each element's `usize` index, and `case` takes string
  literal patterns on text.
- Debug builds check overflow by default; `--no-check-overflow` opts out.
- Literal format templates are checked against their arguments at compile time,
  and run-time templates that do not match print with `{?}` and `{+value}`
  markers instead of printing nothing.
- Structs and plain enums passed by name to a literal template print their
  contents (`Unit{name: ada, at: Vec2{x: 1.5, y: 2}}`), rewritten at compile
  time with no run-time metadata.
- One error shape: statuses never carry an `Error` variant (`io.Transfer` is
  `{transferred, failure, status}`), `std/os` and vendor results replace
  `ok: bool` with `failure: io.Failure`, `bytes/builder` and `fmt` writes are
  sticky and return nothing, sqlite calls return `io.Failure`, and
  `io.failed`/`parse.failed` are the checks.
- Std renames: `mem.arena_alloc*`, `json.push_*`, `box.push_state`; byte search
  lives only in `std/bytes`; `sort.sort_by` and `sort.stable_by`; `fmt.print`.
- Generics: `T{}` names the instance's struct, inference reads through
  function types, and `nil` takes its type from the other arguments, so
  `thread.spawn` and other callbacks take `fn(*$C)` with a typed context.
- `#target(streams: yes)` selects every target with standard streams.
- A local can no longer take the name of a module its file imports.
- The language is frozen until stage 0 ([stability](docs/guide/stability.md)).

## 0.1.0-preview.35

- Native x86-64 SSA release builds propagate cheap uniform scalar arguments
  into readonly parameters of private direct-call helpers, including loops.
  Calls and signatures remain; public functions, escaped callbacks, mutable
  or addressed parameters, conflicting calls, and expensive constants stay
  general. This reuses existing optimizer scans without cloning functions.
- Native x86-64 release code can reuse one runtime quotient for matching
  division/remainder operations. Original checks and panic order remain;
  conservative control-flow and per-function budgets bound optimization work.
- Identical integer operands in comparisons now fold without affecting NaNs
  in floating-point comparisons.
- `dyn docs` resolves missing local `std/...` and `vendor/...` paths through
  the SDK, including `DYN_SDK`, so SDK declaration queries work outside the
  compiler directory. Local paths keep precedence; formatter and build path
  resolution are unchanged.
- Decimal formatting keeps division by ten constant and reuses one quotient
  per digit, allowing existing native strength reduction to avoid hardware
  division. Generic base formatting and decimal output remain unchanged.
- `fmt.write` copies through an exact-length local slice, allowing the release
  compiler to move descriptor loads and redundant destination bounds checks out
  of the byte loop. Capacity failures remain sticky and preserve prior output.
- HTML escaping skips entity lookup for ordinary bytes while preserving
  bounded writes, sticky failures, and the existing five escaped characters.
- Evented HTTP optionally shares fixed overflow send blocks between connections.
  `http.body_buffer` and `respond_buffered` let handlers build bounded response
  bodies directly in transport-owned storage, avoiding a body copy. Pooling is
  disabled by default; existing handlers and configuration keep their behavior.
- `vendor/sqlite` adds `open_with_options` for explicit SQLite open flags.

## 0.1.0-preview.34

- Guarded callback inlining ignores unreachable callback candidates. This
  prevents intermittent native emission failures when unused callbacks have
  local variables, as exposed by DNA's LSP workset tests.
- Preview.33 was cancelled before publication; this release includes its changes.

- `#max(T)` and `#min(T)` are the largest and smallest values of an integer
  type, as constants of that type: write `#max(usize)` for `~#cast(usize, 0)`.
- `dyn vet` reports a `#cast` that its position would make anyway: an
  argument, return value, struct field, typed local, assignment or index whose
  type the value widens to without loss, such as `take(#cast(u64, count))`
  for a `u32` count. Casts that choose a type, like `wide := #cast(u64, n)`,
  are not reported, and neither is a cast that some target needs, such as a
  cast of a `c.char` or `net.Descriptor`. std dropped 751 such casts.
- Binary operators widen the narrower operand when its type converts to the
  other's without loss, as typed slots already do: `count_u32 * size_u64` is
  a `u64`, `index_u32 < limit_i64` compares as `i64`, and `total += count_u32`
  works on a `u64` total. Each operand keeps its own arithmetic until then.
  `u64` against `i64` still needs a cast.
- Release loops whose back edge passes an empty forwarding block, such as a
  loop with a bounds check, now test at the bottom: one branch per iteration
  instead of a compare at the top and a jump back.
- Large programs check about 9% faster and build about 7% faster: the walk
  that finds generic instances in function bodies runs on up to four threads.
- Large programs check about 12% faster and build 7 to 10% faster again. The
  compiler reads each file's `#target` line once, looks modules up by hash,
  hands the optimizer the lowered program instead of a copy, and keeps
  blocks up to 4 MiB in the heap in batch commands instead of mapping each one.
  `dyn lsp` keeps the allocator's defaults.
- Programs with 2048 functions or more check function bodies on worker
  threads, one per 1024 functions up to eight: a 300,000-line project spends
  13 ms in the checker instead of 22, and checks in 95 ms instead of 104.
  Diagnostics, the checked program and the code built from it are the same
  as from one thread; a function that instantiates a generic or reports an
  error is checked again on the main thread, in order. `dyn vet` checks on
  one thread, and `DYN_SEMA_PARALLEL=0` keeps every check there, for
  comparison.
- Release code is tighter: a function that returns a call to itself (or a
  void function ending in one) loops instead of calling, so deep tail
  recursion no longer grows the stack; loops whose condition loads and
  bounds-checks are rotated; `at = (at + 1) & mask` stays in one register;
  64-bit constants used in loops stay in registers; a value kept on the stack
  because it lives across calls is loaded once into a free register for a
  run of straight-line uses instead of at every use. The hash map benchmark
  runs 8% faster, sieve 6%, the JSONL report 3%. A branch around one or two
  cheap instructions that only picks a value becomes a conditional move
  (CMOV on x86-64, CSEL on AArch64), so clamps and min/max no longer
  mispredict. A value can take a register through a stretch where the
  register's owner is dead, so `j -= 1` at the bottom of quicksort's loop
  no longer copies j; the sort benchmark runs 2% faster. An early return
  reached without side effects, such as a recursion's base case or a tree
  walk's `if node.left == nil { return 1 }`, runs before the function saves
  any registers; the tree benchmark runs 3% faster. `for i in a..=b` with
  a constant `b` below the type's maximum compares once per iteration.
  A recursion such as `return fib(n - 1) + fib(n - 2)`, already turned into
  a loop with one call, now copies that loop into its own call six levels
  deep, so most calls never happen; the Fibonacci benchmark runs twice as
  fast.
- Release builds emit machine code on the backend's worker threads instead
  of one thread, and large programs (2048 live functions or more) use up to
  12 workers: a 300,000-line project builds in 199 ms instead of 209. The
  objects are byte for byte what serial emission writes;
  `DYN_SERIAL_EMISSION=1` keeps emission on one thread for comparison. x86-64
  release builds start functions that contain loops on a 16-byte boundary.
- Programs with 512 or more functions run their lifetime checks on worker
  threads after every body is checked, and report the same diagnostics in
  the same order: checking a 300,000-line project's semantics takes 22 ms
  instead of 29. `DYN_SERIAL_LIFETIMES=1` keeps them in place for
  comparison.
- Release builds drop bounds checks that an earlier check already covers:
  after `xs[j]` passed, `xs[..j + 1]` and `xs[j + 1..]` need no check, and
  neither does an index such as `(#len(xs) - 1) / 2` once `#len(xs) >= 1`
  is known. Quicksort keeps only the checks of its inner scans.
- Native builds no longer stop at 32,768 functions and globals or 4 million
  IR nodes: a 1,000,000-line project builds and runs. Release builds of
  large programs are faster again: 300,000 lines in 185 ms.
- Functions that take or return fixed arrays or payload enums by value, such
  as `fn area(shape: Shape) f64`, and functions that call C variadic
  functions now compile to optimized SSA code on every 64-bit target. No
  function in the repository's projects uses the fallback emitter any more.
  `DYN_TREE_FUNCTIONS=a,b` keeps named functions on it, for tests.
- A function that takes a local's address inside a `case` arm now compiles
  to optimized SSA code instead of the simple fallback emitter. std's number
  parsing (`strings.parse_into`, behind `json.read`) was one such function;
  the JSONL report benchmark runs about 7% faster.
- `--release` inlines a little more: each function may grow by 176 cost units
  instead of 128, enough to inline `mem.push` together with the arena's fast
  path. The tree benchmark runs 16% faster; compile time on real projects is
  unchanged.
- `--opt-level 2` and `3` no longer pad x86 function entries to 64 bytes, so
  plain `--release`, which optimizes at the same level, now produces the same
  code as `--opt-level 2`. The padding moved benchmark kernels by -10% to +9%
  depending on where code landed, with no consistent gain.
- `std/os/macos.thread_yield` yields through libSystem's `sched_yield`. It
  called BSD syscall 331, which is `__disable_threadsignal`, not a yield.
- `#syscall` takes a named constant on every Linux target. `std/os/linux/sys`
  and `std/os/macos/sys` name the calls std makes: `#syscall(sys.Openat, ...)`.
- `io.failed(failure)` tests a failure, and `io.linux_failure(code)`,
  `darwin_failure`, `windows_failure` and `wasi_failure` build one from a
  native code with its portable kind.
- `dyn fmt` puts `} else {` on one line. An `if` whose two branches are one
  statement each may be written on one line, `if wide { return 8 } else {
  return 4 }`, and std uses that form where it fits in 100 columns.

- `--release` (O2) now inlines small direct calls the way `--opt-level 3`
  does, within a quarter of its growth budget, instead of only one-statement
  leaves inside loops. An allocation-heavy tree kernel went from 0.79s to
  0.41s, and the JSON log report from 48 ms to 34 ms; compile time of a
  100k-line project did not change. `--opt-level 3` keeps the larger budget
  and adds constant-call specialization and vectorization.
- Calls to `math.sqrt64`, `math.fma64` and the other math functions the
  backend lowers to one instruction are no longer inlined as their software
  bodies.
- `mem.arena_push`, `push`, `push_array` and `arena_push_uninit` take an
  inlined fast path when the current block has room: the tree kernel went
  from 0.41s to 0.29s, ahead of the Go and C versions.
- Release builds drop the bounds check on a probe index that stays in range
  around a loop, such as `at = (at + 1) & (Capacity - 1)`, and reuse a load
  the loop exit already made instead of loading it again.
- A loop counter that calls after the loop push out of registers stays in
  a register inside the loop, and is stored once at each exit instead of
  being loaded at every use. The JSON log report at `--opt-level 3` went
  from 27.8 ms to 26.5 ms.
- Builds without overflow checks turn `return f(n - 1) + f(n - 2)` style
  recursion into one call per level plus a loop, as overflow-checked builds
  already did: release `fib(40)` went from 0.27s to 0.18s.
- `mem.copy`, and any loop of the form `for i in 0..n { d[i] = s[i] }` over
  scalar elements, run as one copy in x86-64 release builds when `n` fits
  both slices (otherwise the loop runs and fails where it did before):
  copying a 1 MiB buffer 2000 times plus 20 million 12-byte copies went
  from 0.45s to 0.07s. Fixed-size zeroing of up to 256 bytes uses 16-byte
  stores instead of `rep stosb`.
- `mem.push` and the other arena pushes take a smaller inlined fast path,
  and a struct's zeroing becomes one fixed-size fill instead of a call:
  the tree kernel went from 0.30s to 0.19s and the JSON log report from
  30.7 ms to 28.3 ms (25.4 ms at `--opt-level 3`). An arena's `peak_used`
  is brought up to date when it is read or rewound, not on every push.
- Threads from `thread.spawn_with_size` on Linux get a 64 KiB guard below
  their stack, so a stack overflow faults (and debug builds report it with
  a trace) instead of writing into neighbouring memory.
- Debug stack traces no longer cost anything per call. Functions no longer
  call `dyn_trace_push` and `dyn_trace_pop` or store their line at each
  statement; instead a panic or memory fault walks frame pointers and looks
  each return address up in a table of function ranges and line rows that
  debug builds carry. Debug `fib(40)` went from 1.39s to 0.33s (C at `-O0`:
  0.28s), and debug binaries are smaller. A trace now lists the innermost
  frames: past 64 it keeps the 48 innermost and 16 outermost and counts the
  rest. Custom runtimes provide `dyn_trace_start(header)`, which `main` calls
  once, instead of `dyn_trace_push` and `dyn_trace_pop`.
- The compiler makes far fewer heap allocations: SSA functions use arenas
  recycled between functions (release builds of a 1500-function project
  went from 179k to 30k allocations, debug builds from 145k to 52k).

- Release builds fold constant globals, including `<<` and `>>` in their
  initializers, so `const Capacity: usize = 1 << 23` no longer loads from
  memory at each use, and a small helper that reads a constant can inline.
  A hash map kernel ran 22% faster. Taking a constant's address still gives
  its `*const` storage.
- Debug builds no longer make two thread-id system calls per function call
  for the stack trace: each thread's trace slot is found from its stack
  address. A call-heavy kernel dropped from 200s to 23s in a debug build.
- Debug index failures also report the index and the length on RV32 and
  Cortex-M targets.
- Debug builds use the SSA code generator on x86-64, AArch64 and RISC-V64
  (Linux, macOS, Windows), as release builds do, with no optimizing passes and
  every local in its frame slot for the debugger. Debug code runs faster
  (nbody 7.7s to 3.2s, matmul 5.6s to 3.6s). Release `--debug-info` builds now
  get optimized SSA code with line rows too. 32-bit targets keep the tree
  emitter in debug builds; `DYN_NO_SSA=1` selects it everywhere.
- A failed index check in a debug build reports the index and the length:
  `runtime check failed (index.ok) in get at main.dyn:6: index 9, length 4`.
- `#cast(u32, 0x80000000)` compiles: an integer literal in `#cast` takes the
  target type when it fits, instead of the default `i32`.
- New `--check-overflow` for debug builds: `+`, `-`, `*`, `<<` and negation in
  the program's own modules panic on overflow instead of wrapping. std and
  vendor code keeps wrapping. New `math.wrapping_add`, `wrapping_sub` and
  `wrapping_mul` mark arithmetic that is meant to wrap.
- `for i in 0..10` with two literal bounds always counts in `usize`. It no
  longer takes the type of the first typed use of `i` in the body, so a use such
  as `total += i` with `total: i32` is now an error at that line. Write
  `for i: i32 in 0..10`.
- Text diagnostics show the source line under each error, with the span
  underlined, and no longer end in `[range L:C-L:C]`. Tools that read ranges
  should use `--diagnostics json`, which is unchanged.
- Error messages name what they are about: `unknown name 'total'`,
  `integer literal is not representable in expected type u8: 300 does not fit`,
  `case is not exhaustive: missing Shape.Rect`, and for a generic call that
  cannot infer a type, the parameter's shape and the argument's type. The old
  wording stays at the start of each message.
- A local whose initializer has an error is still declared, so its later uses
  are no longer reported as unknown names.
- `.Variant` without its enum type reports `an enum variant needs its type:
  write Enum.Variant, not .Variant` instead of a statement-layout error.
- Debug stack traces show the line each frame is running, so a caller's frame
  names the line of its call rather than the function's first line.
- Release builds no longer replace small inputs of Fibonacci-shaped recursive
  functions with a precomputed table. The recursive base-case return remains.
- `tests/run.py` runs tests in parallel (`DYN_TEST_JOBS`, `DYN_TEST_ONLY`);
  `tests/expect/*.dyn` hold diagnostic tests written as `// error:` comments.

- New `std/net/http/evented`: an event-loop HTTP/1.1 server on `std/event`
  (epoll/kqueue). Each worker multiplexes many nonblocking keep-alive
  connections, so slow or idle clients no longer hold a thread. Handlers keep the
  `http.Handler` signature. All buffers are fixed at `evented.start`; see
  `evented.default_config` and `evented.storage_size`. Idle connections close
  after `idle_timeout_milliseconds`; rejected requests get their 400/413 before a
  graceful close.
- `http.respond` now sends the response head and a body of up to 8 KiB in one
  write. Before, the head left in about ten small writes, and keep-alive clients
  waited about 40 ms per response on Nagle plus delayed ACK.
- New `http.frame_request` frames one buffered request without I/O, for servers
  that own their sockets.
- New `net.no_delay` sets `TCP_NODELAY`. The evented server enables it on every
  accepted connection.
- `evented.start_shared` gives every worker its own `SO_REUSEPORT` listener, so
  the kernel spreads connections instead of waking every worker (Linux; other
  platforms report Unsupported). New `net.tcp_listen_ipv4_shared`,
  `net.reuse_port` and `evented.local_port`.
- `std/event` add, modify and remove are now constant time (free list plus a
  descriptor table), and `wait` asks the kernel for at most 512 events per call
  instead of zeroing an array the size of the queue.
- `http.Request` has `path` and `query`, split from `target`. `http.dispatch`
  now matches routes against `path`, so `/search?q=x` reaches a `/search` route.
- New `http.query_value`, `http.form_value`, `http.form_decode` and
  `http.form_field` decode urlencoded fields into caller storage.
  `http.request_header` reads one request header.
- `http.ResponseOptions.headers` adds response headers. A header name that is
  not a token, or a value (or reason or content type) holding CR, LF or NUL,
  fails with `ErrorKind.Invalid` before any byte is written, so request data
  cannot inject headers.
- New `std/html` with `html.write_escaped` for HTML text in `fmt.Buffer`s.
- New `thread.cpu_count()`: CPUs the process may run on (Linux affinity mask,
  macOS `hw.activecpu`, Windows `GetSystemInfo`). Size worker pools with it.
- Typed HTTP state with generics: `http.Typed(T)` and `http.bind` pair a `*T`
  with handlers of type `fn(*Response, *const Request, *T) Result`, so handlers
  no longer cast `Request.context`. A handler for another state type is a
  compile error.
- New generic router `http.Routes(T)` (`typed_routes`, `add`, `bind_routes`,
  `serve_routes`): `:name` path parameters read with `http.param`, 405 with an
  `Allow` header, and a typed fallback. New status constants 201, 303, 401, 403,
  405, 409, 422, 429 and 503.
- `std/html` gains `html.Writer`: `html.text` escapes, and `html.markup` takes
  only `html.Trusted`, made with `html.trusted(...)`. Passing plain bytes as
  markup is a compile error.
- New `parse.u64_decimal` and `parse.i64_decimal`: strict decimal integers
  with overflow and offset reporting.
- Compiler: a malformed generic signature no longer stops later functions from
  being declared, which had produced false "may exit without return" errors.
- New `tools/httpbench`: a Dyn HTTP/1.1 keep-alive load generator
  (`httpbench PORT PATH CONNECTIONS SECONDS`) with p50/p99/max latency.
- Tests: `http-fuzz` fuzzes request framing, form decoding, path matching,
  response header validation and HTML escaping; `http-bench` fails when either
  HTTP server drops below 20000 requests/s or 20 ms p99, which catches stalls
  such as the old 40 ms Nagle delay.
- HTTPS for the evented server: `evented.Config.transport` takes a
  `Transport` (open, handshake, read, write, close) and
  `std/net/http/evented/tls` supplies an OpenSSL one (Linux). Only programs
  importing that module link libssl.
- New `std/thread/posix`: pthread-backed `spawn`, `join` and `spawner()`.
  std/thread's Linux threads carry no libc thread state, so C libraries with
  per-thread state (malloc caches, OpenSSL) corrupt memory when several run at
  once. `evented.Config.spawner` selects the thread creator, and `start`
  refuses a transport marked `needs_native_threads` without one.

## 0.1.0-preview.32

- Generics have one spelling, and existing code needs a rewrite. `tools/migrate-generics.py`
  does it for `.dyn` files:
  - A type the caller passes is `T: type`, or `K, V: type` for several. `$T: type` is an
    error.
  - Struct and enum type parameters are bare names: `struct Map(K, V)`, `enum Slot(T)`.
    Their parentheses hold only types, so `$T: type` and `T: type` are errors there.
  - A type an argument supplies is written `$T` at every parameter that supplies it:
    `fn eql(a: $T, b: $T) bool`. A plain `T` there is an error. The result type and the
    body still write plain `T`.
  - `T: type` for a type that a parameter's type contains is an error; infer it instead.
    `fn first(T: type, items: []T) T` becomes `fn first(items: []$T) T`, and calls drop
    the type.
  - `#instance(f, T, ...)` names an instance as a function value, one type per type
    parameter in declaration order: `#instance(key_hash, u32)`. The old `f(T)` value form
    is gone, so a call `f(...)` always runs the function.

  See [docs/migrations/generics-one-spelling.md](docs/migrations/generics-one-spelling.md).

- A float literal with no float context is now `f64`. `x := 1.5` and a generic `$T`
  inferred from `1.5` were `f32`, which disagreed with `any`. Write `x: f32 = 1.5` where
  you want `f32`; mixing the two in arithmetic is a compile error that points at the line.

- Optimized x86-64 builds no longer miscompile long `else if` chains. Jump forwarding
  stopped after 16 hops, which left some jumps pointing into unrelated functions.
- Several modules may bind the same C symbol when the signatures agree, so a program that
  uses both `std/thread` and `std/process` checks for macOS again. A binding with a
  different signature is still an error.
- A float literal passed through `...any` boxes as `f64`, matching a single `any` parameter
  and the language guide. It was `f32`.
- Debug builds no longer emit dead jumps after a `case` arm or `if` branch that returns or
  panics. When every arm ended that way, the jump pointed into the next function.

## 0.1.0-preview.31

Upgrade guide: [0.1.0-preview.31](docs/migrations/0.1.0-preview.31.md).

- Generic call errors point at your code: a type conflict names the argument that fixed the
  type, and a failure inside a std instance, such as an unsupported map key, is reported at
  your call with the std line as a note.
- The language server treats a lone file that declares `main`, in a directory without
  `main.dyn` or `dyn.project`, as its own program, as `dyn run hello.dyn` does.
- Editor analysis keeps a cancellation that arrives during a struct-literal lookahead instead
  of reporting a syntax error.
- `--opt-level 3` on x86-64 and AArch64 runs counted loops several iterations at a time: four
  `f32` or `i32` lanes, or two `f64` lanes. It covers loads and stores of one-, two- and
  three-field elements, arithmetic (wrapping add, subtract, multiply and bitwise ops for `i32`;
  multiply needs SSE4.1 on x86-64), `f32(i)` of the counter, and running sums. Float sums add
  the lanes in iteration order, so results match the scalar loop bit for bit. The vector part runs only when
  the arrays it writes don't overlap the others and every checked index is in range, both checked
  at run time; otherwise, and for the last few iterations, the scalar loop runs. The `pairs`
  kernel now matches `cc -O2`, and `structs` is 1.14x it, from 1.19x and 1.26x. AArch64 also
  scalarizes small aggregate copies to unaligned destinations, as x86-64 already did.
- Executables keep only what `main` reaches, in debug builds as well as release: unused
  functions, constants and globals from imported modules are no longer emitted, so an unused
  `use` adds nothing to the binary. A global is kept when its initializer could do anything
  besides produce a value (a call, a division, an index or a dereference). `dyn vet` still reports the unused import.
- `fn main() i32` returns the exit code. `process.start()` returns a `process.Program` holding
  `arena`, an arena for the whole program, and `args`. `main` takes no parameters. `dyn run X --
  a b` passes arguments and returns the program's exit code.
- `usize` widens to `u64` and `u32` to `usize` without `#cast`: implicit conversions are those
  lossless on every target, counting `usize`/`isize` as 32 to 64 bits. `u32` to `isize` now needs
  `#cast`, since it loses on 32-bit targets.
- `dyn run hello.dyn`, `dyn check`, `dyn build` and `dyn fmt` take a single `.dyn` file: a module
  of that one file, which stands for `main.dyn`. Other files beside it are not loaded.
- A missing comma between items on separate lines says so:
  "expected ',' or '}', found 'tag': is a comma missing at the end of the line above?".
- Breaking: `map.init(&m, arena)` takes no functions. Integer, enum, bool, pointer and text keys
  hash and compare by value, text by content; another key type is a compile error there.
  `map.init_with(&m, arena, hash, equal)` takes the functions, and `map.init_seeded(&m, arena,
  seed)` and `map.init_seeded_with` take a seed. Migrate `map.init(&m, a, h, e)` to `init_with`.
- `#assert` works in function bodies, checked once per generic instance, and `#typeof(T).kind`
  and the other scalar fields are compile-time constants. `f(T)` with only the leading type
  arguments is that instance as a function value. An `if` on a constant takes its branch at
  compile time.
- Migration notes for the changes below: `docs/migrations/language-rules-20261108.md`.
- Breaking: type patterns drop `is`. Write `i64 n => { ... }`, `Point p => { ... }` and
  `[]const u8 s => { ... }` in a type case; a name that resolves to a type is a type pattern.
  Old code fails with "type patterns do not use `is`"; delete the keyword.
- Breaking: mixing a bitwise operator (`&`, `|`, `^`) with a comparison needs parentheses:
  `(flags & mask) == 0`. The meaning never changes silently, whichever language you came from.
- Comparisons chain in one direction: `0 <= i < n` means `0 <= i && i < n`. The middle operand
  must be a name, field or literal. Mixed directions and `==`/`!=` chains are errors, so
  `a == b == c` now needs parentheses: `(a == b) == c`.
- Generic struct literals: `Box(i32){value: 1}`.
- An inferred constant built from literals adapts to each use like a literal:
  `const LIMIT := 64` fits a `u8`, a `u64` or an `f64`, and a value that does not fit is an
  error at that use.
- `dyn fmt` keeps a one-statement block written on one line: `0 => { return "none" }`.
- Breaking: `io.print` and `io.println` print to standard output and return nothing:
  `io.println("total {}", n)`. `io.eprint`/`io.eprintln` print to standard error. The checked,
  writer-taking forms are `io.print_to(writer, ...)` and `io.println_to(writer, ...)`, which
  return the `Transfer`. Migrate `_ = io.println(io.stdout(), ...)` to `io.println(...)` and other
  writers to `println_to`.
- Struct fields may declare defaults again: `struct Player { health: i32 = 100 }`. Literals fill
  omitted fields, `p: Player` starts from the defaults, and `mem.push` writes them; types without
  defaults pay nothing. `#init(pointer)` writes a type's defaults for custom allocators.
  `mem.try_push` writes them too. `mem.push_array` and fixed arrays stay zeroed;
  `mem.push_array_init` gives every element the defaults, with the loop visible at the call.
- Plain enums may set tags: `enum(i32) Errno { Ok = 0, NoEnt = 2, Io = 5 }`. Tags increase and
  start at 0; an unset tag follows the previous one. Reflection's `TypeMember` gains `value`,
  the variant's tag, and `enums.from_int`/`enums.name` respect set tags.
- A nested block may shadow an outer local or parameter: `if ready { x := parse(x) }`. A second
  local with the same name in one block, or shadowing a loop variable inside its loop, is still
  an error. `is` is no longer reserved.
- A literal range takes its type from the loop variable's first typed use: in
  `for i in 0..5 { total += i }` with `total: i32`, `i` is `i32`. Otherwise it is still `usize`.
- Literals boxed into `any` take default types, as in Go and Odin: `i32`, `f64`, `[]const u8`.
- `std/panic`: `panic.set_handler(report)` runs once after cleanups and before an unhandled panic
  reports and exits, for logs and crash reports. Panics remain unrecoverable.
  On Wasm a panic still traps at once, so the handler does not run there.
- A body-less declaration's return type must start on the same line as its `)`, so
  `extern fn f(x: i32)` followed by a global on the next line no longer misparses, in the compiler and in editors.
- Breaking: `io.Result` is now `io.Transfer`. `io.Result(T)` and `parse.Result(T)` are the
  generic `{value, failure}` results, and named result types are aliases of them.
- `std/container/map`: `map.Map(K, V)`, a growing hash map for any key type. Set it up with
  `map.init(&m, arena, hash, equal)`, then `insert`, `get`, `upsert` and `remove`.
  `upsert(&m, key, initial)` returns the value, adding `initial` when absent, so
  `map.upsert(&counts, word, 0).* += 1` counts in one lookup. Walk a map with
  `it := map.walk(&m)` and `for map.next(&it) { ... it.entry ... }`. `insert` returns
  nothing; use `upsert` or `get` for the value's address.
- `std/container/array`: `array.Array(T)`, the everyday growing list. `array.init(&a, arena)`,
  then `push`, `push_ref`, `push_all`, `get`, `pop` (a `{value, ok}` result) and `clear`;
  `a.items` is a plain slice.
  Arrays share arenas and double when full.
- The vectorized `c[p + j] += v * b[q + j]` loop runs on one index with one branch per vector, as
  GCC and LLVM lay it out: matmul now runs level with `cc -O2`. Small struct copies split into
  word moves on AArch64 too, so field stores there reach forwarding and pairing.
- Opt-level 3 on x86-64 and AArch64 computes pairs of adjacent `f32` fields together: `ps[i] = V{x: ..., y: ...}`
  built from the same operations on each field becomes one 8-byte load, lanewise SSE arithmetic and
  one 8-byte store, and `a.x * b.x + a.y * b.y` over such pairs a lanewise multiply and an in-order
  add. Results match the scalar code bit for bit.
- Release builds keep a loop total and its update in one register when the total is read after
  the loop, so `e += x` in a loop no longer copies the total twice per iteration.
- Release builds inline a call to the right of an operand the call may change, as in
  `total + step()`: the operand is read into a temporary first, so the order is unchanged.
- Release builds call a stored function directly, and inline it, when it is the only function of
  its type the program ever takes. A comparison keeps any other value correct.
- Release builds keep more values in registers around rarely taken calls, reuse loads across
  branches, and skip pointer checks on element addresses that flow through a variable. Branches
  on a boolean that comes through several paths jump straight to their targets, and jumps
  through empty blocks go straight to where they land. A loop counter times a constant, such as
  an index scaled by a struct size, steps by an add instead of a multiply, and a counter kept only
  for its bound test is replaced by the scaled one. A loop that branches on
  a value fixed before it runs as two copies, and register allocation treats paths that can only
  end in a failure as cold. Calls inside loops inline at up to twice the usual size, including
  calls whose result is dereferenced, such as `map.get(&m, key).*`. At `-O3` the inliner ranks
  call sites by how often they run for their size, so a call in a loop gets the budget before a
  rarely run one that comes first, and a large callee behind a branch, such as a resize, stays a
  call. Register allocation counts loop depth from real loops, so an inlined call's frame no longer
  looks like a loop, and a spilled value a loop reads gets a register through that loop, taken
  if need be from a value the loop does not use, which goes back at the loop's exits.
- `chunk.List(T)` replaces the two structs a chunk list needed.
- Generic structs: `struct Box($T: type) { value: T }`, used as `Box(i32)`.
- Debug builds report memory faults with a stack trace on macOS and Windows too. On Windows a
  stack overflow still ends the process (0xC00000FD) without the report.
- The documentation test now type-checks complete examples.
- Generic enums: `enum Slot($T: type) { Empty, Full: T }`, used as `Slot(i32).Full(7)`.
- Release builds at opt-level 3 vectorize `for x in xs { t += x }` and `t += x * x` and `for i in 0..n { t += xs[i] }` over 32- and 64-bit integer slices on x86-64 and AArch64 (squares are 32-bit only).
- Opt-level 3 also vectorizes `for j in 0..n { c[p + j] += v * b[q + j] }` over `f32` and `f64` slices, when the range is in bounds. Results match the scalar loop exactly.
- An enum payload may be another enum.
- Enum payloads are back: `enum Node { Null, Number: f64 }`, built with
  `Node.Number(2.5)` and read only through `case`. The first variant has no payload,
  and explicit enum values stay removed.
- Linux debug builds report memory faults with a stack trace and exit 101.
- Debug builds report the source line of a failed runtime check.
- Breaking: float to integer `#cast` saturates on every target, and NaN gives 0.
  It was target-defined, and trapped on Wasm. `math.float_to_int_sat` is removed;
  use `#cast`.
- Breaking: std results use one shape. `std/errors` moves into `std/io`, effects
  report `io.Failure`, and parsers report the new `parse.Failure`. See
  `docs/migrations/result-shape.md`.
- Breaking: struct field defaults are removed. `struct S { n: i32 = 4 }` is now
  a compile error. Every struct starts from zeros on every path, so make zero a
  useful value, set the field in the literal, or use a named constant.
- Breaking: `distinct`, `packed` and `is` are always reserved. `stb_rect_pack`
  renames `Rectangle.packed` to `was_packed` and `Result.packed` to `count`.
- Breaking: a character literal with no expected type is now `u32`, never `u8`.
  It adapts to any integer type the value fits.
- Range loops accept a typed binding: `for i: i32 in -3..3`. Breaking: a range
  with two literal bounds and a negative one needs it. It no longer picks `isize`.
- Breaking: enum values and payloads are removed. Variants are always 0, 1, 2 in
  order. Use constants or a translation table for external numbers, and a struct
  with a `kind` field for sum types.
- Breaking: integer `+`, `-`, `*`, `<<` and negation wrap instead of panicking, and
  `#wrap` is removed. Shift counts are masked. `#cast` to an enum no longer checks
  the value; an exhaustive `case` still panics on a bad tag. Division checks stay.
  Use `math.add_overflows` and friends where overflow matters.
- Breaking: `pointer[..count]` is replaced by `#slice(pointer, count)`.
- New: `#offset(pointer, count)` and pointer ordering, for walking memory.
- New: pointer-free `union` types. `union` is now a reserved word.
- Breaking: `mem.append` never moves a list and panics at the end of its block.
  `mem.append_grow` keeps the old moving behavior; `mem.try_append` returns a stub.
- New: `std/enums`, `math.div_or_zero`, `math.rem_or_zero`.
- `dyn vet` reports unused locals and imports. `dyn vet --unsafe` lists unsafe operations,
  including size multiplication that can wrap.
- See `docs/migrations/prefreeze-language.md`.
- `ui.Style` no longer has built-in colors. Write
  `ui.Context{ style: ui.default_style }`; a zero style draws nothing.
- Zero is now the safe state for handles. `fs.File`, `net.Connection`,
  `net.Listener`, `signal.Watch` and `watch.Watcher` hold `0` when closed, so
  test `active` or `is_open`, not `descriptor == -1`.
- `capability.Directory` needs `active: true`. A zero value fails with EBADF
  instead of using file descriptor 0.
- `process.CaptureOptions`: a zero timeout now means infinite, not immediate.
  Set the new `no_wait` for an immediate timeout.
- `text.layout.Options`: `wrap` and `normalize` become `no_wrap` and
  `no_normalize`. Zero `tab_columns` means 4, as it does in the vendor layout,
  where zero `base` also means Auto.
- `harfbuzz.Options.item_length` applies only with `has_item_length: true`.
- `vulkan.open`: a zero limit selects the built-in limit.
- `timer.SysTick{}` no longer has a base. Use `&timer.systick`.
- `x509.View.path_length` is meaningful only when the new `has_path_length` is
  true. It was `-1` when absent.

## 0.1.0-preview.30

This release is source compatible with preview.29. No code migrations.

- "Unknown type in parameter" and "unknown type in global declaration"
  diagnostics now span the type itself (`*App`), not the `: ` before it.
  Editors underline the right text.
- The SDK ships GDB pretty-printers at `share/gdb/dyn.py`. They print strings
  and slices bounded by `len` (`"hey"`, `len 2 = {1, 2}`) instead of reading
  `data` as a NUL-terminated C string. Load them with
  `source <sdk>/share/gdb/dyn.py`; see `docs/guide/debugging.md`.

## 0.1.0-preview.29

This release is source compatible with preview.28. No code migrations.

- `fs.read_all` sizes its first allocation from the open file's reported
  length. Regular files are read into one exact allocation instead of growing
  geometrically, so earlier copies no longer stay pinned in the arena until
  the caller rewinds. Files that change length while being read, FIFOs and
  pseudo files that report zero still use the growing path.
- Linux arena blocks advise the kernel not to back their first 2 MiB with
  transparent huge pages. On systems with THP set to `always`, each small
  arena previously faulted a full 2 MiB page on first use; 32 small arenas
  now cost about 128 KiB resident instead of 64 MiB. Larger arenas still use
  huge pages past their first 2 MiB.
- `#syscall(28, ...)` (`madvise`) is mapped for AArch64 and RISC-V Linux
  targets.

## 0.1.0-preview.28

This release preserves preview.27's pointer-handle, chained arena API. Upgrade
the compiler, SDK, native adapters and editor integrations together.

- Imports remain module-wide. Identical imports across files are deduplicated;
  different aliases for one dependency no longer produce cross-file vet findings.
  Conflicting aliases and same-file duplicate diagnostics remain. Import path
  resolution is reused across repeated declarations.
- Reduced compiler allocations and repeated import work; parallelized frontend
  and backend passes. The language server reuses unchanged rewritten sources
  across edits. Compile-cost budgets now guard allocations and peak memory.
- Added fallible `mem.arena_try_create`, `arena_try_create_bounded` and
  `arena_try_push_uninit` using pointer handles. Fallible pushes and extension
  report Windows commitment failure without publishing a partial allocation.
- Added portable filesystem metadata, directory operations and file mappings;
  portable readiness queues, process signals and watchers; SIMD helpers and
  expanded media, serialization, cryptography and certificate APIs.
- Added `std/ui/box`: persistent keyed boxes, layout, animation, scrolling,
  virtual lists, keyboard focus, text selection and composed desktop widgets.
- Added TrueType font discovery, composite outlines, rasterization and optional
  HarfBuzz/FriBidi layout with grapheme wrapping, source-cluster queries and
  visual selection rectangles. Added batched OpenGL rendering.
- Expanded desktop window backends with ordered input, clipboard transfers,
  worker wake-ups, translated keys, IME composition, surrounding-text correction
  and portable native frontend controls. Wayland, X11, Win32 and Cocoa remain
  subject to the native qualification scope documented in the release evidence.
- Preserved preview.27's JSON/parser optimizations and shared-unwind fixes while
  integrating the development SDK. Added regression and native qualification
  coverage for the expanded APIs.

## 0.1.0-preview.27

Upgrade guide: [0.1.0-preview.27](docs/migrations/0.1.0-preview.27.md).

The preview.26 publication was cancelled before assets were published; upgrade
directly from preview.25 to preview.27. The earlier tag is retained for traceability.

- Fix Linux x86-64 shared-runtime linking when a module has no unwind table. Weak
  table boundaries resolve safely to zero; populated tables retain their range
  through image-base relocations in the built-in ELF linker.

- **Breaking arena API:** constructors return `*mem.Arena`, with the header in
  backing storage. Pass the pointer directly rather than `&arena`. Explicit
  `arena_create(0)` selects the target default; zero arena values no longer
  initialize themselves. Owned arenas chain blocks, while caller-buffer arenas
  stay fixed. Release invalidates an owned handle. The separate `GrowingArena`
  and `arena_take` APIs are removed. See [arena migration](docs/migrations/arena-handles-20261025.md).

- **Breaking syntax:** each statement starts on its own line; `a := 1 b := 2` and
  `defer { x() y() }` are syntax errors. Split them onto separate lines.
- **Breaking syntax:** `case` arms are no longer separated by commas. Delete the
  `,` after each arm's closing `}`.
- **Breaking syntax:** a function's name is its value. Write `write: buffer_write`
  instead of `write: &buffer_write`; `&function` is now an error.
- Literals that do not fit their context are compile errors, including `-1` for
  an unsigned type and inside generic instances. Integer literals work in float
  contexts when exact, so generic code can write `value < 0` and `x * 2` instead
  of `#cast(T, 0)` and `#cast(T, 2)`.
- Restored `dyn build --emit-ir` as versioned structural Dyn IR, with deterministic byte encoding and atomic `--output` files. This does not emit LLVM IR.
- Standard-library contract corrections: buffered I/O, INI and WebSocket state retain their first failure; zero SHA-256 contexts initialize lazily; failed Metadesk parses return the stub; sort searches return the input length on a miss.
- Breaking API migrations: flags parsing, regex compilation and thread creation take arenas first. Thread creation returns a stable arena-backed pointer. See [migration notes](docs/migrations/std-contracts-20261024.md). Flags, regex, URL, semver, PNG and QOI expose portable error categories and native error codes; codec payloads are under `value`. Remaining std migrations are tracked separately; these changes do not establish universal compliance.
- **Breaking:** DNS answer collections, complete HTTP exchanges/chunk decoding,
  process capture and AEAD outputs now use caller arenas. Capture limits are
  explicit policy. HTTP/WebSocket controls, TLS, terminal operations and
  capability reads return portable results; protocol diagnostics remain separate
  from native codes. Watchers retain terminal failures. Zero PRNG and HTTP worker
  states are safe, and worker startup takes an arena for stable thread nodes.
- **Breaking:** clock reads, sleep, deadlines, profiling completion and benchmark
  queries return structured failures; duplicate `try_*` clock names are removed.
  OS clock failures propagate through network waits and process capture. CSV,
  XML and TAR retain portable stream diagnostics. Text/HTML template exhaustion
  follows the arena panic contract.
- Trusted standard math calls use target-gated native instructions in tree,
  SSA and Wasm emission. Unsupported operations keep portable implementations.
  Native x86 optional instructions require CPU and OS capability checks.

- Expanded `std/math` with integer bit/overflow/saturating helpers, portable
  floating-point functions, concrete vectors, column-major matrices,
  quaternions and half-open ranges. Vector normalization widens intermediates;
  matrix inverses and fallible constructors return `{value, ok}`. Floating
  accuracy is checked by sampled host-libm comparisons and selected RV32/Thumb
  cases; these tests do not establish a global transcendental error bound.

- **Breaking:** `process.Options{}` is valid and inherits every stream.
  Streams are `process.Redirect` values made with `process.redirect(handle)`;
  `process.options()` is removed.
- `bytes/builder.Builder` keeps its first error in `error` and `fmt.Buffer`
  sets `failed`; later calls do nothing, so callers may check once at the end.
  `clear` resets both.
- A zeroed `watch.Watcher` is inactive and `close` leaves descriptor 0 alone.
- New `tools/std-lint.py`, run by the test suite, flags `_into` forms, size
  companions, out parameters and `-1` positions in std.
- **Breaking:** one result shape at the edges. Single-payload results name
  the payload `value`: `fs.FileResult`, `OffsetResult`, `ReadAllResult`,
  `PathResult`, `DirectoryResult`, `AtomicResult`; `net.ConnectionResult`,
  `ListenerResult`, `http.AcceptResult`; `process.SpawnResult`,
  `ArgumentsResult`; `testing.TemporaryResult`; `watch.OpenResult`; `zip`
  `EntryResult`, `ExtractResult`, `OpenResult`; DNS address results; `xml` and `ini`
  scanner results; `semver`, `template`, `der` and `certificate` results.
  Network, watch and temporary-directory results gain `kind`. Parser results
  use portable `kind`, native `error`, and byte `offset`. Module-specific parser
  diagnostics use `detail`; `ini` also retains its line number. JSON and Metadesk
  retain `root` and return their read-only stub on failure.
- **Breaking:** one way to produce variable-size data: the function takes
  `arena: *mem.Arena` first and returns the result in it. Removed the
  caller-buffer forms and size companions: `strings.clone_into`, `join_size`,
  `join_into`, `split_count`, `split_into`; codec `encoded_size` and
  `decoded_size`; `zstd.compress_into` and `decompress_into`; `tls`
  `*_create_into`; `c.string_from_arena` (now `string_from_bytes(arena,
  source)`). Converted to arena-first: `strings.replace`, `fmt` number
  formatting, hex/base32/base64 `encode` and `decode`, JSON `encode`,
  `encode_pretty` and `write_string`, `path` and `url` builders,
  `time.format_iso8601`, `debug.hexdump`, `flags.usage` and `completion`,
  Unicode `case_fold` and `normalize`, HTTP and WebSocket writers, DNS queries,
  `tls.certificate_subject` and `error_string`, `deflate.inflate` (new
  `gunzip`), `gzip.decompress`, `zip.extract`, `png` and `qoi` codecs,
  `pem.decode`, `process.environment`, `fs.read_link`, `fs.app_directory` and
  `testing.temporary_*`. Wrap fixed storage with `mem.arena_from_buffer`.
  Fixed-size results and streaming reads keep caller buffers. New
  `mem.trial_size` and `trial_next` for producers of unknown size.
- The 32-bit SSA backends now accept `main`'s call to the global initializer
  instead of falling back to the tree emitter.
- **Breaking:** positions are `usize` and a miss returns the length, which is
  always a safe slice bound: `bytes.find`, `find_byte`, `find_last`,
  `find_last_byte`, the `strings` wrappers and `search.find`. The compiler now
  rejects `x < 0` and `x >= 0` on unsigned values, which catches leftover `-1`
  checks.
- **Breaking:** typed reads. `strings.parse(T, text)`, `strings.parse_base(T,
  text, base)` and `strings.valid(T, text)` replace `parse_u64`, `parse_i64`,
  `parse_f64` and `parse_u64_base`; bad input gives zero. `json.get(T, value,
  key)` and `json.as(T, value)` read members as integers, floats, bools,
  strings or nested values.
- **Breaking:** JSON lookups return the read-only `json.nil_value` stub
  instead of nil, and a failed parse returns it as `root`. Kind zero is now
  `KindMissing`; the other kind constants moved up by one. `mdesk.nil_node` is a
  read-only constant.
- **Breaking:** results are returned, not written through out parameters:
  `bytes.split_next`, `strings.scan_until/scan_field/scan_line`,
  `text/scanner.next_line/next_field`, `utf8.next`, `utf8/utf16.codepoint_count`,
  the `decoded_size` functions, `time.parse_iso8601`, `terminal.read_state` and
  `terminal.raw`, and `ring.pop` return `{value, ok}`. `rand.below` returns the
  value and panics on an invalid limit. `path.Component.found` is now `ok`.
- **Breaking:** containers are intrusive. New `std/container/list` (stacks,
  queues, doubly linked lists, trees and free lists through `next`, `prev`,
  `first`, `last`, `parent` and `free_next`), `std/container/hash` (chained
  slot tables through `key`, `hash` and `hash_next`, with seeded SipHash-1-3)
  and `std/container/chunk` (chunk lists on a shared arena). `slot_map` now
  works on the caller's slot array through a `generation` field. Removed:
  `std/container/string_map`, `mem.Pool`, `mem.FreeList` and their functions.
  See `docs/migrations/containers.md`.
- **Breaking:** `mem.append(arena, &items, value)` replaces
  `mem.append(&items, &count, &arena, value)`. The slice must be the newest
  allocation in its arena. Appends extend it in place when possible, but move
  it when it outgrows a block; reacquire element pointers and views afterward.
  Appending after another allocation panics. New `mem.append_many`.
- Unknown field errors name the type and field: `Node has no field 'prev'`.
- **Breaking:** function types drop the `*`: write `fn(i32, i32) i32`, not
  `*fn(i32, i32) i32`. Parameters may be named for documentation:
  `fn(target: *Entity, damage: i32) bool`. `*fn(...)` now means a pointer to
  a function value. See `docs/migrations/function-types.md`.
- Taking the address of a constant gives a `*const T` into read-only data, so
  constants work as shared read-only stubs: `const nil_node: Node = Node{}`
  and `&nil_node`. Writing through it is a compile error.
- New experimental target `thumbv7em-none`: bare-metal images for Cortex-M7
  (Thumb-2, double-precision FPU, AAPCS with floating-point registers),
  tested on the QEMU `mps2-an500` board. It uses the same 32-bit model as
  `riscv32-none`. The runtime assembler and the ELF linker now handle Thumb
  code and Arm relocations. The value corpus of 3,249 cases matches x86-64
  Linux in debug and release builds (`just test-native-thumb`).
- New experimental target `riscv32-none`: 32-bit bare-metal images for the
  QEMU `virt` board (RV32GC, ILP32D). The native backend now handles 32-bit
  pointers and `usize`: 64-bit values use register pairs, and 64-bit division,
  checked multiplication and integer/float conversions call start-runtime
  helpers. The ELF linker reads ELF32 objects and writes ELF32 executables.
  The value corpus of 3,249 cases matches x86-64 Linux in debug and release
  builds (`tools/backend/bare-differential.py`).
- Importing a member of a module that has no source file for the target now
  reports the missing module once, instead of "imported member is missing".
- `std/strings`, `std/path`, `std/encoding`, `std/crypto/der`,
  `std/crypto/password`, `std/text/regex`, `std/net/http` and
  `std/net/websocket` no longer assume a 64-bit `usize`.
- `distinct`, `packed` and `is` are contextual keywords. They stay keywords at
  the start of `distinct type`, `packed struct` and a `case` type pattern, and
  are ordinary names everywhere else. `type` stays reserved.
- Type mismatch errors name the full types, for example
  `expected *u8, found *i32` instead of `expected pointer, found pointer`.
- `mem.append` grows the arena's newest allocation in place instead of copying,
  through the new `mem.arena_try_extend`. A slice built in a loop with nothing
  else allocated in between now costs its final size, not twice that.
- Legacy typed pools are superseded by the caller-owned intrusive containers
  described above; `mem.Pool` and `mem.FreeList` are removed.
- `tests/bare-metal.py` kills the QEMU process group on timeout. A trap raised
  while reporting a trap on `riscv64-none` exits with status 103 instead of
  trapping again.

- Every enum now needs a variant with value 0, so zeroed storage is always a
  valid variant. Enums such as `enum(u8) Op { Add = 1, Halt = 0xFF }` must add
  one, for example `None = 0`, and handle it in exhaustive `case` statements.
  An exhaustive `case` that sees an invalid tag now panics with `enum.tag.ok`
  instead of executing an illegal instruction.
- Documented binary operator precedence. Bitwise operators bind tighter than
  comparisons, unlike C.
- Handle cleanup now follows one convention: `close(&handle)` or
  `release(&handle)` takes a pointer and clears the handle. Renamed:
  `tls.config_destroy(c)` to `tls.config_release(&c)`,
  `tls.connection_destroy(c)` to `tls.connection_release(&c)`,
  `tls.certificate_free_owned(c)` to `tls.certificate_release(&c)`, and
  `dynlib.close(h)` now takes `&h`. `net.listener_close` and
  `net.connection_close` clear the descriptor even when close fails, so a
  reused descriptor is never closed twice. New `net.listener_take` and
  `net.connection_take`. `dyn vet` now also warns on copies of std handle
  structs.
- `net.Connection` and `net.Listener` gain an `active` field, so zeroed storage
  is a closed handle; closing one no longer closes descriptor 0 (stdin).
  Construct from a raw descriptor with `net.connection_from_descriptor` or
  `net.listener_from_descriptor` instead of a struct literal, and test
  `handle.active` instead of `handle.descriptor >= 0`.
- New `mem.try_push(T, &arena)` and `mem.try_push_array(T, &arena, count)`
  return nil or an empty slice instead of panicking when the arena is
  exhausted. The memory guide documents per-request budgets and that std never
  rewinds partial output on failure.
- New `mem.append(&items, &count, &arena, value)` grows any typed slice, and
  `slot_map` gains `init_for`, `insert_value` and `get_value` for typed records
  without casts. Generic structs remain deferred.
- `net.Result`, `dns.Result` and `watch.Result` gain a portable
  `kind: errors.Kind`, matching `fs`. New `net.error_kind(code)` maps a native
  socket error code. DNS NXDOMAIN reports `NotFound`.
- `dyn fmt` now owns indentation: two spaces per enclosing bracket, one extra
  level for a line continuing an expression, and closing brackets at their
  opener's level. Block comment interiors are untouched. Run `dyn fmt` once;
  `dyn fmt --check` reports code that only differs in indentation. All std,
  runtime and vendor modules are now formatted and checked in CI.
- Fixed two undefined-behaviour bugs found by the new `just sanitize-test`
  gate: formatting a file with no layout edits, and language-server import
  completion in a module with no other sources.
- Clearer diagnostics: `#reverse` outside a `for` iterable, and a type
  parameter written `$T` more than once in one signature.
- The language guide now defines assignment and literal evaluation order, what
  `string` guarantees about UTF-8 (nothing, without validation), and shallow
  `*const` with an example.

- Empty caller-buffer arenas and zero-capacity subarenas now remain fixed at
  zero capacity instead of silently allocating OS backing. Reset, rewind, and
  transfer preserve this mode. Release clears the descriptor to the lazy default;
  use `arena_from_buffer` again before reusing it under a fixed budget. `Arena`
  gains a `fixed_buffer` field; rebuild consumers rather than relying on its
  previous binary layout. Memory documentation now distinguishes fatal cleanup
  from retryable thread errors and accounts for zeroing and page commitment costs.

- **Breaking syntax change:** conversions now use `#cast(Type, value)` and
  `#bitcast(Type, value)`. The old prefix forms are rejected with a migration
  diagnostic. Conversion behavior is unchanged; the operand is evaluated once.
  Cast results support ordinary postfix operations. SDK sources, generators,
  examples, and language-server snippets use the new forms. See the
  [cast syntax migration](docs/migrations/cast-syntax.md).
- `http.serve_stream` and `http.serve_connection` now answer a malformed
  request with `400 Bad Request` and an oversized one with
  `413 Payload Too Large` before closing the connection. Before, the client
  saw the connection close with no reply.
- Fixed `http.receive` waiting for more input forever after a complete
  request head that does not parse. It now returns `ErrorKind.Invalid`.
- Added `tests/flagship-http`, a notes server on four worker threads using
  `Request.context` for its state, checked
  with concurrent keep-alive clients, pipelined requests and bad input.
- Added `tests/flagship-game`, a headless Breakout that renders every frame
  through a per-frame arena. The test checks that debug and release builds
  produce identical frames, that frames retain no memory, and that the game
  core builds for `wasm32-browser`, `aarch64-linux`, `x86_64-windows` and
  `aarch64-macos`.
- Added the experimental `riscv64-none` target: static bare-metal images for
  the QEMU `virt` board, with no operating system. Output goes to the board's
  UART, arenas take memory from a fixed region after the image, and a panic or
  a return from `main` ends QEMU with the program's exit status. `std/mem`,
  `std/io` and the modules built only on them work; modules that need an
  operating system do not. See [bare metal](docs/guide/bare-metal.md).
- The built-in ELF linker accepts a load address. Bare-metal images place code
  first at that address and do not load the ELF headers.
- `dyn docs` creates its temporary output in `TMPDIR` and reports when it
  cannot, instead of exiting silently.
- `just sanitize-test` instruments only the compiler, so C helpers the tests
  build no longer load the ASan runtime into Dyn programs.
- **Breaking:** fallible memory functions now all use the `try_` prefix, and
  the plain names panic, matching `arena_push` and `arena_try_push`:
  `growing_push` (was `growing_push_or_panic`) and `growing_try_push` (was
  `growing_push`), `growing_try_push_uninit` (was `growing_push_uninit`),
  `pool_acquire` / `pool_try_acquire`, and `free_list_alloc` /
  `free_list_try_alloc`. The `_or_panic` names are gone.
- Signed integers can index arrays and slices and bound slices, as in C, with
  the same bounds check: a negative index panics with `index.ok`. Types wider
  than `usize` (such as `i64` on 32-bit targets) still need `#cast`.
- Using a module with no source file for the target (for example `std/process`
  on `wasm32-wasi`) reports one error naming the module instead of an error
  for every missing name inside it.
- Added `std/mmio` for memory-mapped device registers: `load_u8` through
  `load_u64` and `store_u8` through `store_u64` take an address and perform
  exactly one access each, never removed, merged or cached by the compiler.
  Each access is one call into the runtime support object.
- HTTP handlers can reach application state without module globals:
  `http.Request` has a `context: rawptr` field, set by the new
  `http.serve_stream_context`, `http.serve_connection_context` and
  `concurrent.start_context`. The existing functions pass nil.
- Added a Dyn port of the fail-fast source parser in `tests/selfhost-parser`,
  the first self-hosting step. `tests/selfhost-parser.py` checks that it
  produces the same tree, node for node, as the C parser on every `.dyn` file
  in the repository and on generated broken and deeply nested inputs.

## 0.1.0-preview.25

- The compiler no longer uses Tree-sitter. Its handwritten parser handles every
  command and the language server, and source builds no longer need the
  Tree-sitter library or a grammar checkout. Editor highlighting still uses the
  separate `tree-sitter-dyn` grammar.
- LLVM is no longer a compiler dependency. Debug, release, browser Wasm and
  WASI builds use independent code generation and built-in linkers. The retained
  LLVM backend and C++ ThinLTO bridge are removed; `--backend llvm` now reports
  an error. Source builds require a C11 compiler and Python. Optional LLVM tools
  remain useful for validating exported assembly in tests.
- Release builds for x86-64 and AArch64 on Linux and macOS, RISC-V64 Linux and
  Windows x86-64 and ARM64 generate code through an SSA optimizer and register allocator.
  Typical loops run two to three times faster (more on RISC-V64) and binaries
  are about 30% smaller. Runtime checks, their order and their messages are
  unchanged. `DYN_NO_SSA=1` selects the previous code generator, and
  `--opt-remarks` reports functions that still use it.
- Small structs passed, returned and built as literals in release builds stay
  in registers instead of going through stack memory. Code that works on small
  structs runs faster, and binaries are about 3% smaller.
- Release builds unroll and jam loop nests that sum floating-point products,
  such as matrix multiply: two outer iterations share each inner loop. Results
  are bit-identical, and the matrix multiply benchmark runs twice as fast.
- Recursive functions that return `f(...) + x` on unsigned 64-bit integers, such
  as Fibonacci, loop on their last call instead of recursing. Overflow still
  panics with the same message.
- RISC-V64 release calls preserve structs split between the final argument
  register and the stack, including arguments following the struct.
- Default release builds inline small leaf functions inside loops. Argument
  evaluation, assignment targets, overflow checks and deferred cleanup retain
  their original behavior; constant data is shared instead of duplicated.
- On x86-64 Linux and macOS, unsigned recursive base cases can return before
  setting up a frame. Pure two-branch additive recurrences also specialize their
  first eight inputs when those results are proved non-overflowing.
- `--emit-ir` is removed; use `--emit-asm` to inspect generated code. The
  LLVM-syntax writer behind it was the last LLVM-shaped code in the compiler.
- Native targets include Linux x86-64, AArch64 and RISC-V64, macOS x86-64 and
  AArch64, and Windows x86-64 and ARM64. Runtime objects are generated directly,
  without a target assembler. macOS output carries an ad-hoc signature; Windows
  DLLs include base relocations and short-format import libraries.
- Release O3 adds direct-call inlining, integer local register allocation on
  x86-64/AArch64 Linux and macOS, and fixed-bound integer array SIMD loops using
  SSE2/NEON. Unsupported cases retain scalar code and stack storage. These
  improvements do not promise LLVM-equivalent performance on every workload.
  See the independent toolchain guide for exact limits and benchmark commands.
- Builds reuse complete executable cache entries. The removed ThinLTO pipeline
  no longer supplies per-module native cache reuse. `--no-cache` still forces
  rebuilding; `--no-lto` is accepted for command-line compatibility.
- ELF linking supports anonymous symbol visibility scripts, RUNPATH, x86-64
  lazy binding, and executable thread-local storage for supported x86-64 C
  object relocations. Large heap layouts no longer inherit the stack-frame
  size limit. These fixes support DNA's native dependencies.
- Syntax errors name the offending token and what was expected (for example
  `expected ')', found 'bar'` instead of `invalid syntax near 'ERROR'`). The
  parser resumes at the next statement or declaration and reports up to 20
  errors per file, in `dyn check`/`build`/`run` and in editors.
- Stricter syntax: errors in files whose `#target` excludes the current
  platform are now reported (they were ignored); NUL bytes anywhere and invalid
  UTF-8 in string or character literals are errors; string literals may not
  span lines. String literals containing `//` or `/*` (such as `"//x"`), which
  the grammar could reject, are accepted. The 1024-level nesting limit is
  measured on the new parser's tree and can be one level stricter.
- Language server: syntax diagnostics list every recovered error. Selection
  ranges skip redundant nested ranges, and completion inside partially written
  statements resolves more local and field types. Recovery from broken code is
  per statement, so a broken statement contributes nothing until it parses.

## 0.1.0-preview.24

Compatible with preview 23, except that calling `main` is now an error.
Checked arithmetic and runtime safety guarantees are unchanged.

- Debug builds on x86-64 Linux generate machine code directly instead of through
  LLVM: 3 to 10 times faster on generated 100k-line, 500k-line and 4,000-file
  projects. Executables keep the same runtime checks, panic traces and DWARF
  debugger information (lines, frames, parameters and typed locals). Programs the
  native code generator cannot handle fall back to LLVM automatically.
  `--backend llvm` restores the old behavior; `--backend native` makes a
  fallback an error. Debug builds for AArch64 Linux, AArch64 macOS and x86-64
  Windows use the same native code generator, and compilers on macOS and ARM
  Linux hosts include it. Release builds and Wasm still use LLVM. On macOS the
  object `<output>.dynnative.o` stays beside the executable so debuggers can
  read its DWARF. Windows debug builds carry DWARF for GDB and LLDB, as LLVM's
  Windows debug builds do, and unwind tables for every native function.
- Native debug information shows each local only within its scope, and payload
  enums as `tag` plus a `payload` union.
- The compiler parses sources with a handwritten parser, making `dyn check`
  about 1.9 times faster with 40% less peak memory on large projects. Files with
  syntax errors are still reported through the Tree-sitter grammar, so
  diagnostics are unchanged. Editors keep Tree-sitter.
- Float remainder (`%` on `f32`/`f64`) no longer needs libm: the runtime
  provides exact `fmod` and `fmodf`.
- Calling `main` is now a compile error (`entry function 'main' cannot be
  called`). It reran global initialization: debug builds overflowed the stack
  and release builds looped.

## 0.1.0-preview.23

Compatible with preview 22. Checked arithmetic and runtime safety guarantees are
unchanged.

- `dyn check` validates module references in parallel and avoids repeated
  lifetime-analysis work. When multiple modules contain invalid references,
  diagnostics now report all affected modules.
- Builds compute shared code-generation metadata once instead of repeating
  whole-program scans for each module. Constant-success safety guards no longer
  emit unnecessary branches.
- The pinned Tree-sitter grammar removes redundant expression, literal and
  statement wrapper nodes, reducing syntax-tree memory and conversion work.
  Tools that consume these nodes must update their queries; Dyn source syntax
  is unchanged.
- `--timings` includes peak memory after each phase.
- `tools/compare` provides repeatable compile-time, runtime and memory comparisons
  with Go, C and Odin, plus an HTML report generator.

## 0.1.0-preview.22

Breaking.

- `dyn vet DIR` checks a module and reports suspicious but valid code: copying
  an arena, and importing one module under two names. It exits 1 when it finds
  something. `check`, `build` and `run` now report errors only, and
  `--warnings-as-errors` and `--no-warnings` are removed; run `dyn vet` in CI
  instead. Language servers still show vet findings as warnings.
- The CSV, INI and XML scanners keep their first error in the scanner. After
  an error `next` returns `ok: false`, so loop until `ok` is false and then
  check `state.error` once. The per-item `error` fields are gone from
  `csv.Field`, `ini.Result`, `xml.Result` and `xml.Attribute`.
  - `csv.Scanner` and `csv.StreamScanner` gain `error`; `Scanner` also records
    `error_offset`. A stream read failure is `ErrorKind.Io`, with the system
    code in `system_error` (previously `error`).
  - `ini.next` skips a malformed line and keeps going. The scanner records the
    first error and its `error_line`, and counts all of them in `errors`.
    `ini.parse` still fails when any line is malformed.
  - `xml.StreamScanner` gains `error`; read failures are `ErrorKind.Io`
    instead of `Syntax`.

- Zero is initialization across std:
  - A zero `mem.Arena{}` reserves address space on its first push (64 GiB,
    4 MiB on wasm32), so it works without `arena_create`. Release it with
    `arena_release`.
  - A zero `GrowingArena` has no capacity limit. `growing_create_bounded(n, 0)`
    now means unbounded rather than "only zero-size pushes".
  - `text.Scanner` line and column are zero-based; add one for display.
  - `ini.Scanner.line` counts lines read (entry and error lines stay 1-based).
  - `csv.StreamScanner.pending` became `record_ended`.
  - `process.Options` still uses -1 for "inherit": 0 is a real descriptor.
    Build it with `process.options()`.

## 0.1.0-preview.21

Breaking.

- Arena pushes cannot fail. `mem.arena_push`, `arena_push_uninit` and
  `arena_push_array` return `*u8` and panic when a fixed arena is exhausted,
  like `mem.push`. `arena_push_or_panic` and `arena_push_uninit_or_panic` are
  removed; drop the suffix. `mem.arena_try_push` is the one push that reports
  exhaustion, for code with a strict budget.
- `strings.clone`, `join`, `split`, `format`, `format_arguments` and
  `list_join` return the bytes directly; `list_push` and `list_push_format`
  return nothing. A bad format template and an empty split separator panic.
  The caller-buffer forms (`clone_into`, `join_into`, `split_into`) keep their
  results.
- Arena-backed `builder.reserve`, string maps and `ini.parse` panic instead of
  reporting `Capacity` when their arena is exhausted, and `json`, `ini` and
  `string_map` drop their now-unused `ErrorKind.Capacity`.
- `#wrap(expression)`: integer `+`, `-`, `*`, unary `-` and `<<` written
  inside wrap around instead of panicking on overflow. Division and shift
  counts are still checked. Use it for hashes and random number generators.
- Enums take explicit values: `enum(u8) Op { Add = 1, Sub, Halt = 0xFF }`.
  Values are integer literals and must fit the tag type; a variant without a
  value is the previous one plus one. Enums with payloads keep implicit values.
- `#cast` converts a plain enum to an integer, and an integer to an enum. The
  integer-to-enum cast panics when the value is not one of the variants.
- `hash.hash64` is now 64-bit FNV-1a, so its values change.

## 0.1.0-preview.20

Compatible with preview 19.

- Fixes an intermittent crash in release builds: the optimizer pass that
  splits structs into separate values read freed memory, which LLVM builds
  with assertions reported as a `cast<PHINode>` failure.

## 0.1.0-preview.19

Breaking. See [`docs/migrations/0.1.0-preview.19.md`](docs/migrations/0.1.0-preview.19.md).

- Generic functions with `$T` type parameters. `std/mem`, `std/math` and
  `std/sort` use them: `mem.push(T, &arena)`, `mem.push_array`,
  `mem.clear`, `math.min`/`max`/`clamp`/`abs`/`narrow`, `sort.sort`.
- Allocation is arena-only. The allocator interface and the `#alloc*`
  builtins are removed.
- `mem.arena_create` reserves address space and panics instead of returning
  a result. Release, frames, sub-arenas, pools and free lists follow; Windows
  commits on demand.
- `#assert(condition, "message")` checks constants at compile time, and
  `#offsetof(Type, field)` gives a field's byte offset.
- `#load("file")` embeds a file's bytes as a string.
- `use "a" x, "b" y` imports several modules in one `use`.
- New std: `strings.format`, `strings.List`, `mem.Frames` and the
  Metadesk parser `std/encoding/mdesk`. `std/slice` is removed.

## 0.1.0-preview.18

- A mutable `*T` now converts to `rawptr` implicitly, like C's `void *`:
  `free(task)` replaces `free(#cast(rawptr) task)`. Existing casts still
  compile; delete them at your convenience. `rawptr` to `*T` and `*const T` to
  `rawptr` still require `#cast`.
- Faster `dyn check` and builds: modules are parsed in parallel and only once,
  builds analyze the program once instead of once per module, and large
  modules are compiled in parallel chunks. Debug builds emit less code for
  runtime checks.

## 0.1.0-preview.17

- Fix using `std/io` standard streams and `std/os/wasi` together: shared raw
  declarations prevent duplicate foreign symbols without changing public APIs.
- Fix debug builds where a hoisted stack slot retained another function's debug
  location and LLVM rejected the module.
- See the [migration guide](docs/migrations/0.1.0-preview.17.md) for standard
  stream replacements in older examples and explicit arena ownership transfer.

## 0.1.0-preview.16

This release changes allocation names and adds typed allocation. Follow the
[migration guide](docs/migrations/0.1.0-preview.16.md) before updating callers.

- Breaking local API cleanup: ordinary allocation builtins and arena operations
  return failure; `_or_panic` explicitly selects panic on failure. Existing callers,
  editor help, and examples are migrated. See the [memory guide](docs/guide/memory.md).
- Add fallible pool/free-list construction, allocator-output strings and INI
  parsing. Growing allocator callbacks no longer zero payloads redundantly.
- Keep lifetime diagnostics narrow. No borrow checker, ownership annotations,
  automatic reclamation, or implicit allocator is introduced.

- Add experimental primitive `Allocator`, fixed-callback construction, typed
  allocation builtins and `#AllocResult` with named `AllocError` categories.
  Fixed/growing arena adapters, reflection, editor support, failure tests, and
  design documentation accompany the feature.

`std/mem` adds binary byte units `KiB`, `MiB`, and `GiB`, plus
`size_for(count, element_size)`. Check the returned `ok` before using `bytes`:
overflow returns failure instead of trapping, and zero count or element size
succeeds with zero bytes. The result describes payload only, excluding alignment
padding and container metadata. Allocation naming changes are listed below.

Fixed-array types now accept integer constants and simple nonnegative constant
arithmetic, such as `[4 * mem.KiB]u8`, including imported constants. Runtime-sized
stack arrays remain unsupported. Constants needed by exported layouts and public constants are preserved
transitively in module interfaces, including dependencies from other files.
Unrelated private constants remain excluded.

`arena_push_array` checks count multiplication and performs zeroed aligned
allocation while retaining explicit element size, alignment, and pointer casts.
`arena_take` transfers a fixed-arena descriptor and clears the old slot. Direct
copies of known arena descriptors warn; use `--warnings-as-errors` for a hard gate
or `--no-warnings` to suppress these warnings. Existing reset diagnostics now also
recognize literal `arena_rewind(..., 0)`. These are narrow checks, not borrow checking.

Growth remains explicit. `growing_create_bounded` limits total requested backing
bytes, `growing_snapshot` reports retained storage, and `growing_trim` releases
empty blocks without invalidating live allocations. Reset still retains blocks.
Trim and release preserve remaining ownership after partial failure.

`dyn docs --json` adds `contracts` summaries sourced from labelled adjacent comments.
The schema remains version 1 with additive fields; full comments remain available.
The new [memory guide](docs/guide/memory-patterns.md) is exercised in debug and release
by `tests/documentation-examples.py`.

## 0.1.0-preview.15

`std/testing` imports work on macOS and Windows again: Linux-only temporary
directory and path helpers are isolated behind their target guard.

Release debug information now permits inlining. New opt-in `--cpu native`,
`--opt-level 3`, `--opt-remarks` and x86_64 Linux ThinLTO `--sample-profile`
controls support measured tuning; portable O2 remains the default. CPU features
and profile contents participate in cache identity.

The standard library adds prepared allocation-free linear-time byte search,
string-map reservation/clear and caller-owned sample statistics. Byte search
filters mismatching tails, large buffered writes avoid staging copies, and byte
builders extend the last arena buffer in place when possible. Existing storage,
overlap and failure contracts remain covered by regression tests.

`tools/performance-suite.py` records isolated cold, unchanged, novel-edit and
runtime samples with executable size and per-child memory measurements. See the
README for tuning, profiling and ownership contracts.

## 0.1.0-preview.13

### Reuse release-link optimization

On x86_64 Linux with LLD, release builds now emit real ThinLTO summaries and
module hashes. Previously, plain bitcode silently selected full LTO and repeated
whole-program optimization whenever linking ran. Native backend results now use
a periodically pruned cache; `--no-cache` bypasses it and `--jobs` limits backend
workers as well as frontend workers.

In a local LLVM 23 comparison on DNA, a cached relink fell from 4.50 seconds to
0.52 seconds. Cold builds and root-module edits still took about 6.4 seconds;
this change does not claim the same speedup for those workloads. Cache reuse and
dependency invalidation were also checked with LLVM/LLD 19.

Building the compiler from source now needs a C++ compiler and LLVM development
headers for the small ThinLTO writer. Packaged SDK users need no additional tools.

## 0.1.0-preview.12

### Compiler correctness and scaling

Bounds and overflow proofs now discard facts invalidated by branches, calls,
indirect writes, or loop-carried assignments, and respect the target pointer
width. Compound assignment evaluates its destination once. Floating-point
inequality handles NaN correctly. Forward global initializers and dependent
struct/enum layouts resolve in dependency order, and type-capacity overflow
reports an error instead of corrupting interned types.

Function/global lookup, module declaration lookup, source locations, and guard
propagation avoid repeated whole-program scans. Range-analysis scratch is scoped
to each function. String constants use bulk LLVM construction. Cache accounting
includes retained frontend storage and estimated syntax-tree storage; executable
cache keys include the selected runtime objects. LSP semantic tokens avoid
repeated expression scans and repeated UTF-16 prefix conversion.

### Reliable native deferred cleanup

Windows and macOS unwind state is isolated by thread. Panic unwinding restores
Windows XMM6–XMM15 and floating-point controls, and AArch64 d8–d15, so deferred
cleanup retains its floating-point values. Context sizes follow the target ABI;
Linux x64 keeps its existing 128-byte context.

### Standard library performance and fixes

Compiled regex matching uses an iterative machine with workspace independent of
input length. Streaming deflate uses circular history. String-map deletion closes
probe gaps, slot-map insertion skips the occupied prefix, and arena-backed pools
use optional occupancy bits for constant-time release. HTTP readers scan fragmented
headers and chunk framing incrementally. JSON output escapes control bytes, JSON
string decoding releases unused arena space, and decimal formatting avoids
rounding large integral doubles incorrectly.

**Regex migration.** `regex.Match` now includes `error: MatchError`, with `None`
and `Capacity` variants. Check `error` before treating `ok == false` as no match.
`find_compiled` uses 4096 `usize` workspace slots; larger programs should allocate
`match_workspace_size(program, capture_count)` slots and call
`find_compiled_workspace(program, text, captures, workspace)`. This API performs
no hidden allocation and clears captures on failure.

**Allocator and container layout.** `mem.FreeList` gains `occupied: []u8`, and
`slot_map.SlotMap` gains `next_free: usize`. Use their initializer functions rather
than depending on struct layout. Pool occupancy storage is optional: caller-buffer
and exact-capacity arena initialization retain their existing usable capacity and
linear validation fallback. Rebuild consumers that depend on these layouts.

The regression suite now covers allocation failures, compiler miscompilations,
cache retention, fragmented HTTP, regex capacity, pool ownership, deflate history,
and native unwind register preservation. Local Linux checks and cross-target ABI
harnesses pass; the release workflow separately requires native platform checks
and validated SDK packages before publication.

### Faster, private `memcpy`, `memmove` and `memset`

The runtime's `memcpy`, `memmove` and `memset` copied one byte at a time and
were exported from every executable. A program that also linked a C library and
shared libraries (SDL, FreeType, GPU drivers) replaced the C library's versions
for all of them. They now move eight bytes at a time, use `rep movsb`/`rep
stosb` for blocks of 512 bytes or more on x86-64, and have hidden visibility,
so each shared library keeps its C library's versions. No code changes are
needed. Projects that hid these symbols with a linker version script can keep
it; it is no longer required.

### Process exit runs C exit handlers

A program that links the C library now ends through its `exit`, so `atexit`
handlers run and buffered `printf`/`puts` output is flushed. Before, the
runtime exited with a raw syscall and output written to a pipe or file was
lost. Programs without the C library exit with `exit_group`, which also ends
other threads. `os.exit_process` in `std/os/linux` uses `exit_group` too; it
used to end only the calling thread.

### Dyn functions may share a name with an extern's C symbol

A Dyn function named like the C symbol of an extern in another file of the
same module, such as `pub fn free` next to `extern fn libc_free "free"`, failed
to link with an undefined `free.1`. The Dyn function now gets a private symbol
and both resolve.

### Global shadowing is checked in imported modules

A parameter named like a global was rejected in the root module but accepted
in imported modules. Both now report one error, "parameter has the name of a
global; shadowing is forbidden", without a follow-on "unknown name" for each
use. Rename the parameter if an imported module stops building.

### Numeric literals adopt the other operand's type on either side

A literal on the left of an operator defaulted to `i32`, so `8 + step` with
`step: u32` failed with mismatched types while `step + 8` built. The literal
now takes the other operand's type on either side, for arithmetic, bitwise and
comparison operators. Casts written to work around this can be removed.

### Hex literals containing `e` or `E` are integers

`0x1E1E2E`, `0xE` and any other hex literal with an `e` or `E` digit were read as
floating-point numbers, so `x: u32 = 0x1E` failed with "expected u32, found
f32". They are now integers like every other hex literal.

## 0.1.0-preview.11

### `#reverse` for-in loops

`#reverse` walks a range, array, or slice from its last value to its first:

```dyn
for i in #reverse(0..count) {   // count - 1, ..., 1, 0
  _ = values[i]
}
for i in #reverse(1..=count) {  // count, ..., 2, 1
  _ = i
}
for value in #reverse(values) { // last element first
  _ = value
}
for *item in #reverse(values) { // mutate from the end
  item.* += 1
}
```

- `#reverse` visits exactly the values of the forward loop, in the opposite
  order. `#reverse(0..0)` and `#reverse(5..2)` run no iterations.
- Unsigned bounds never wrap: `#reverse(0..=n)` stops after `0`.
- `#reverse` is valid only as a `for` iterable. `reverse` remains an ordinary
  name.
- A descending range such as `5..2` still runs no iterations. Use `#reverse`
  to count down.

**Migration.** Replace manual down-counters:

```dyn
i := count
for i > 0 {
  i -= 1
  work(i)
}
```

with `for i in #reverse(0..count) { work(i) }`. Convert only when `i -= 1` is
the first statement of the body, the body never assigns `i` or takes `&i`, and
`i` is not used after the loop. `continue` is safe here, because the manual loop
already decremented before it.

### Editor completion

Completion details for declarations with quoted text, such as
`extern fn poll "SDL_PollEvent"(...)`, no longer show doubled escapes.
`#reverse` appears in completion and has hover documentation.

## 0.1.0-preview.10

### Range for-in loops

`for` accepts an integer range after `in`:

```dyn
for i in 0..count {    // 0, 1, ..., count - 1
  _ = values[i]
}
for i in 1..=count {   // 1, 2, ..., count
  _ = i
}
```

- Both bounds share one integer type. A literal bound adapts to the other bound,
  so `0..count` has `count`'s type and `0..#len(values)` is `usize`.
- When both bounds are literals, the binding is `usize`, or `isize` if a bound
  is negative. `for i in 0..3 { values[i] }` indexes directly.
- Bounds evaluate once, first bound first. `5..2` runs no iterations.
- The binding is a copy. Assigning it inside the body does not change the
  iteration. `for *i in 0..n` is an error.
- `..=` may end at the type's maximum. `for b in 250..=top` with `top: u8 = 255`
  runs 6 times without overflow.
- Mixed bound types such as `u8..u32` are an error: "range bounds require the
  same integer type".

**Migration.** Replace manual counter loops:

```dyn
i: usize = 0
for i < count {
  work(i)
  i += 1
}
```

with:

```dyn
for i in 0..count {
  work(i)
}
```

Convert only when all of these hold, or behavior can change:

1. `i += 1` is the last statement of the body.
2. The body never assigns `i` or takes `&i`.
3. The body has no `continue`. In a manual loop `continue` skips the
   increment; in a range loop it advances to the next value.
4. `i` is not used after the loop. A range binding exists only inside the loop.
5. The body cannot change the end bound. The manual loop rereads `count` on
   every iteration; the range reads it once. Keep manual loops whose end is a
   field reached through a pointer, a global, or a local whose address is taken.

Loops that step by more than one, count down, or change the counter inside the
body stay as condition loops.

### Names are reusable after their scope ends

A local declared in a block or loop no longer reserves its name for the rest of
the function. Consecutive loops can each use `i` or `value`, and a name can be
declared again after an earlier block ends:

```dyn
for value in first {
  _ = value
}
for value in second {
  _ = value
}
```

Shadowing is still forbidden: a local cannot reuse the name of a visible local
or parameter, including an enclosing loop's binding.

**Migration.** Names such as `i2`, `index_b`, or `value_2` that only avoided the
old rule can go back to the natural name. Previously, redeclaring a name after
its block also reported a spurious `unknown name` at the redeclaration; that is
gone.

### Standard library

122 std counter loops now use range loops. No public API changed.

## 0.1.0-preview.9

### `dyn fmt` works on real modules and enforces layout

`dyn fmt DIR` used to run full semantic checks without loading imports, so any
module with `use` failed with "unknown name" errors. It now only requires every
file to parse, validates all files before writing any, and reports the first
syntax error per file.

`dyn fmt` and editor formatting now apply:

- One statement per line. `if ready { return }` becomes three lines, and
  `x := 1 y := 2` is split.
- One space after every comma: `add(4, 2)`, `[1, 2, 3]`. No space is added
  before a closing bracket or at a line end.
- LF line endings, no trailing spaces or tabs, and a final newline.

The formatter only inserts or removes whitespace between tokens, so it cannot
change behavior. Running it twice changes nothing.

**Migration.** `dyn fmt --check` now fails on code that passed on preview 8.
Run `dyn fmt DIR` for each module directory and commit the result
separately from other changes. Add `dyn fmt --check DIR` to CI. Write new code
in this layout: two-space indent, one statement per line, a space after commas,
`snake_case` functions and locals, and `PascalCase` types, enum variants, and
constants.

### Editor formatting

LSP formatting returns only the changed lines, returns no edits for an already
formatted or malformed document, and answers requests for unknown documents
with `null` instead of leaving the client waiting.

### Editor completion

Top-level completion no longer analyzes the whole project. A completion request
queued behind edits is answered before project-wide diagnostics run.

### Building the compiler

These affect only people building `dyn` from source:

- `tools/build.py` compiles one object per source file in parallel. Set the
  worker count with `JOBS=n` or `--jobs n`.
- Linker flags in `CPPFLAGS` (`-L`, `-l`, `-Wl,`) are passed to the link step
  only.
- The WASI runtime objects use the `wasm32-wasip1` target.

### Standard library

std was reformatted with the new layout rules. No public API changed.
