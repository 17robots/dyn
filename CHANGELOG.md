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

- Added optional FriBidi paragraph resolution and HarfBuzz shaped layout with script/font runs, grapheme-safe wrapping and source-cluster queries. HarfBuzz now supports explicit run properties and full-line context; FreeType exposes scalable-face metrics.
- Software rendering skips blending for fully opaque pixels. X11 exposes checked swap interval control for immediate presentation or refresh pacing.

- X11 clipboard snapshots now support up to 16 MiB through bounded INCR transfers. `try_set_clipboard`, `paste_pending` and `paste_status` expose copy/receive failures; large ordered replies overflow atomically instead of publishing a prefix.

- Added revision-checked `std/text/edit`, ordered IME replacement events, and textbox correction handling. Wayland, Cocoa and Windows IMM publish bounded surrounding text; Windows supports selected-range reconversion and X11 explicitly returns `Unsupported`. Stale revisions, invalid UTF-8 ranges and capacity failures preserve caller text.

- Ordered composition snapshots and clipboard chunks now own their payloads, preserving multiple updates before draining. Composition has one portable 272-byte ABI; Event remains 312 bytes. XIM caret/locale/bounds, IMM Unicode conversion and Wayland transactions/disable are hardened. Text fields suppress IME-consumed keys, preview selected replacement without insertion, redraw on preedit changes and publish current-layout candidate rectangles.

- Input method composition: `vendor/window` reports preedit text and cursor and places candidate windows at the caret (`set_text_input`) on X11 (XIM callbacks or over-the-spot), Wayland (`text-input-v3`), Win32 (IMM) and Cocoa (`NSTextInputClient`). `std/ui/box` text fields draw the composition at the caret and request text input placement.
- `vendor/window` adds opt-in ordered raw key/text events, explicit queue overflow and worker wake-ups on X11, Wayland, Win32 and Cocoa. Event text is caller-owned; existing `box_input` summary clients retain their idle behavior. IME preedit and candidate placement remain unsupported.

- `std/ui/box` exposes current-frame `find`, explicit `key_bytes`, portable `key_number` identities and persistent caller `user_data`, allowing applications to share the keyed cache and recycling policy with custom renderers.

- `std/ui/box` adds mouse and Shift selection, Unicode word movement/deletion, selected clipboard operations, atomic replacement and horizontal scrolling in text fields. Tab/Shift-Tab traverse controls; Enter activates buttons. Tabs, popup menus, tooltips and splitters compose existing boxes. `layout`/`render` can run separately for custom app renderers, with container padding, absolute positioning and optional ordered shrinking.

- `std/font/system` scans platform or explicit font directories, reads owned family/style metadata, matches weight/slant and selects fonts covering missing code points without fontconfig. Unsupported collections and CFF faces are skipped. `examples/box-viewer` now discovers its default font instead of requiring a Linux path.

- `std/fs` directory listing, `metadata`, `file_metadata`, `remove`, `rename`, `make_directory` and `remove_directory` now work on macOS and Windows, not only Linux. Fixed: `open_directory` failed on Linux AArch64, which uses a different `O_DIRECTORY` value.
- Desktop input now works on every `vendor/window` backend: Wayland (xkbcommon text with compose and key repeat, `wl_data_device` clipboard, cursors, output scale), Win32 (UTF-16 text and IME output, clipboard, cursors, DPI) and Cocoa (text, clipboard, cursors, backing scale; untested until macOS CI runs). Paste arrives on the poll after the request on every backend.
- `vendor/window` on X11 adds UTF-8 text input through the input method, editing keys, wheel scrolling, the clipboard, cursors, display scale, `wait` for idle loops and `box_input`. `examples/box-viewer` is a 100,000-row log viewer on `std/ui/box`.
- `ui.rounded_rectangle` and `Command.radius` draw antialiased rounded rectangles. `vendor/ui/opengl` adds a batched renderer: one signed-distance shader, a cached glyph atlas, and a draw call per clip.
- `std/ui/box` adds a box-model UI after the RAD Debugger design: keyed boxes, semantic-size layout, previous-frame input, animation, text fields, scrolling and virtual lists.

- `std/text/layout` adds NFC-aware Unicode line layout, Latin pair kerning, wrapping,
  alignment, tabs and soft hyphens. `std/ui/text` emits positioned glyph commands.
- `std/embedded/uart`, `timer` and `interrupt` replace board-only helpers with
  reusable polling UART, CLINT/SysTick and nested critical-section APIs. RV64 heap
  alignment and RISC-V assembler immediate validation are corrected.
- Portable codecs add WAV, BMP/TGA/PPM/PGM read-write, first-frame GIF and baseline
  JPEG decode, TOML 1.0 parse/write, and CBOR/MessagePack/protobuf wire APIs.
- `vendor/window` adds native X11, Wayland, Win32 and Cocoa windows with UI input.
  OpenGL presents UI commands; Vulkan provides an offscreen compute renderer.
  FreeType/HarfBuzz bindings add native rasterization and directional run shaping.
- Authenticated encryption, X25519, Ed25519 and P-256 now use native Dyn; SHA-512
  and explicit Ed/P-256 X.509 path validation are included. TLS retains its separate
  OpenSSL provider. Low-level AEAD supports exact in-place payload operation.
- HMAC rejects oversized keys correctly. HKDF/PBKDF2 reject overflowing lengths
  and mutable/borrowed overlap before writing; callers must provide disjoint
  destination, scratch and borrowed key/info/password/salt slices.
- Wasm emission reuses completed aggregate temporaries, avoiding local-count
  exhaustion on large or nested literal arrays.
- Native expansion/UI qualification is wired into macOS and Windows CI; real
  native execution and physical-board qualification remain release gates.

- TrueType rasterization now expands composite outlines with affine transforms, contour-point attachment, nested components and horizontal metric selection. Graph and coordinate budgets bound expansion; cycle/truncation failures preserve arena state. Phantom-point attachment and rotated selected metrics remain unsupported.

- Initial `std/font` support loads TrueType cmap/metrics and rasterizes simple quadratic outlines into caller arenas, with bounded supersampling and atlas packing. `std/font/ui` renders direct or cached glyphs through the portable UI backend. Full OpenType and complex-script shaping remain outside the portable font parser.

- `std/ui` adds a pure-Dyn immediate-mode core with buttons, checkboxes, integer sliders, pointer capture, keyboard focus and arena-owned draw commands. `std/ui/software` renders RGBA output with caller-provided glyph coverage; a headless PNG example is included.
- Wasm emission now respects function liveness after O3 inlining, avoiding invalid bodies referencing replaced IR tables.

- `std/simd` adds ten portable 128-bit lane types, per-lane wrapping arithmetic, masks and checked loads/stores, using existing O3 SIMD lowering where supported.
- Generic instance symbols now distinguish nominal types from different modules, including nested compound types.

- `std/event` adds caller-owned readiness queues over epoll, kqueue and WSAPoll, with tokens and deadline-preserving waits.

- IPv6 and Unix stream helpers, IPv4 UDP multicast membership and options, and loopback regression coverage. Unix paths reject embedded NULs.

- `testing.fuzz` replays a corpus, then mutates it and shrinks failures; `testing.Source` decodes structured values from fuzz input.
- `std/math/big` adds arbitrary-precision integers in the caller's arena.
- `std/unicode/text` adds `word_breaks` (UAX #29) and `line_breaks` (UAX #14), passing all Unicode 17 conformance cases.
- `std/time` converts between instants and calendar dates (`date_time`, `instant_of`, `weekday`, `day_of_year`). `std/time/zone` adds time zones, local time and formatting.
- `std/thread/pool` runs tasks on a fixed set of workers over a bounded queue in the caller's arena, with `Group` wait groups.
- `fmt.write_f64_shortest` and `fmt.f64_shortest` print the shortest decimal that parses back to the same `f64` (a Ryu port). `{}` formatting is unchanged.
- `std/process/signal` reads Ctrl-C, SIGTERM, SIGHUP and Windows console close events as queued events, with no code in signal handlers.
- `fs.map` and `fs.unmap` give read-only views of whole files on Linux, macOS and Windows.
- `std/hash` adds `wyhash` (final version 4.3) and `crc32_update`; `crc32` is table-driven.
- `std/terminal` and `std/dynlib` now work on macOS and Windows as well as Linux.
  `terminal.State` grows to 72 bytes to hold the Darwin termios layout.
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
- **Breaking:** `mem.append(&arena, &items, value)` replaces
  `mem.append(&items, &count, &arena, value)`. The slice owns the rest of its
  arena, so appends never copy and element addresses never change; it panics
  when something else was pushed on that arena. New `mem.append_many`.
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
- Typed pools: `mem.pool_for(T, &arena, count)`, `mem.acquire(T, &pool)`
  (zeroed `*T`) and `mem.release(&pool, item)`.
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
