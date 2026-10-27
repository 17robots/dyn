# Standard library

Every std package is ordinary Dyn source shipped with the SDK. The source is the
API reference: `dyn docs std/strings` prints a module's public declarations and
their contracts, and `dyn docs std/strings --json` gives the same as JSON.

## Conventions

- **No hidden allocation.** A function that needs memory takes a `*mem.Arena`
  or a caller slice. Ordinary arena pushes panic when exhausted (`mem.try_push`
  reports it instead); caller-slice functions report `Capacity` with the exact
  size `required`. See [memory](memory.md) and
  [buffer contracts](buffer-contracts.md).
- **Borrowing is the default.** Returned slices borrow the input, the caller's
  buffer or the arena, as each function's comment says. Reader-backed scanners
  return views that last until the next call.
- **Zero is initialization.** A zeroed struct is a valid empty value: `Arena{}`,
  `Builder{}`, `GrowingArena{}`, `process.Options{}` (inherit every stream),
  scanners given only their `source`. Constructors exist for convenience, not
  because zero is broken.
- **Errors are values, in one shape.** Results at the edges (OS, files,
  network, processes) are `{value, ok, kind, error}`: `value` is the payload,
  `kind` a portable `std/errors` category and `error` the native code. Test
  `ok` first, then branch on `kind`; compare `error` only for platform-specific
  handling. Parsers of external input use the same portable `kind` and native `error`,
  plus an `offset`. Pure parsers use native error `0`; an optional `detail`
  preserves a module-specific diagnostic. Tree parsers (`json`, `mdesk`) name
  the payload `root` and return a usable stub on failure. Migration status
  and remaining exceptions are tracked in [std standardization](../internals/std-standardization.md).
  Scanners and writers keep their first error in their state and turn later
  calls into no-ops, so callers check once at the end. Predicates return
  `bool`. Missing lookups and end of input are ordinary results, not errors.
- **Panics are for bugs.** Broken invariants, out-of-bounds access and
  exhausted arenas panic. There is no recovery.
- **Native resources are explicit.** Files, sockets, threads, loaded libraries
  and provider handles have their own close or join. Resetting an arena closes
  nothing.

## Packages

### Memory, bytes and text

| Package | Purpose |
| --- | --- |
| `std/mem` | Arenas, typed pushes, `append`, scratch scopes, frames and growing arenas |
| `std/bytes` | Byte-slice operations, cursors and splitters |
| `std/bytes/builder` | Byte and UTF-8 string builder over caller storage or an arena |
| `std/bytes/search` | Prepared KMP search |
| `std/strings` | Search, parse, split, join, format, glob, ASCII helpers and string lists |
| `std/fmt` | Formatting into a bounded caller buffer, including shortest round-trip floats |
| `std/unicode/utf8`, `utf16`, `text` | Strict UTF-8 and UTF-16, case folding, normalization, and grapheme, word and line segmentation |
| `std/text/scanner` | Line and field scanner with positions |
| `std/text/regex` | Thompson-NFA regular expressions compiled into an arena; reusable workspace |
| `std/text/template`, `std/html/template` | Text templates, and HTML templates that escape text and quoted attributes |
| `std/container/list` | Intrusive stacks, queues, doubly linked lists, trees and free lists |
| `std/container/hash` | Intrusive chained hash tables and seeded SipHash-1-3 |
| `std/container/chunk` | Chunk lists that grow on a shared arena without copying |
| `std/container/slot_map` | Generation handles into caller slot arrays |
| `std/container/ring`, `bit_set` | Ring buffer and bit set over caller storage |
| `std/sort` | In-place sort and binary search for any ordered element type |
| `std/simd` | Portable 128-bit integer and floating-point lanes; supported O3 operations use SSE2/NEON |
| `std/math` | Scalar arithmetic, bit helpers, concrete vectors, matrices, quaternions and ranges |
| `std/math/big` | Arena-backed arbitrary-precision integers: arithmetic, division, shifts, bases, bytes, `power_mod` and `gcd` |
| `std/hash` | Stable non-cryptographic hashes (FNV-1a, wyhash), CRC-32 and checksums |
| `std/rand` | Deterministic caller-owned PRNG; not for cryptography |

### Encoding and formats

| Package | Purpose |
| --- | --- |
| `std/encoding/json` | Validation, arena-backed mutable DOM parsing, queries and writing |
| `std/encoding/json/read` | [Experimental compact read-only DOM](json-read.md), with arena-owned values and text |
| `std/encoding/csv` | RFC 4180 field scanner, stream scanner and writer |
| `std/encoding/ini` | INI scanner and one-pass `parse` into an arena table |
| `std/encoding/toml` | TOML 1.0 arena-owned tree, queries and normalized writing |
| `std/encoding/xml` | XML document trees, event scanner, attributes, namespaces and writer |
| `std/encoding/mdesk` | Metadesk-style labeled trees with tags |
| `std/encoding/hex`, `base32`, `base64` | Codecs into caller buffers that validate before writing |
| `std/encoding/binary` | Fixed-width endian and unsigned LEB128 encoding |
| `std/semver` | Semantic Versioning 2.0 values |
| `std/compress/deflate`, `gzip`, `zstd` | DEFLATE encode and decode, gzip members, zstd compress and decompress |
| `std/archive/tar`, `zip` | TAR (ustar, PAX, GNU) and ZIP reading |
| `std/image/png`, `qoi`, `color` | PNG and QOI encode and decode, with caller RGBA storage |
| `std/image/bmp`, `tga`, `gif`, `jpeg` | BMP/TGA read-write, first-frame GIF and baseline JPEG decode |

### Operating system

| Package | Purpose |
| --- | --- |
| `std/io` | `Reader`/`Writer` callbacks, standard streams and `print`/`println` |
| `std/bufio` | Buffered readers and writers over caller storage |
| `std/fs` | Files, directories, metadata, atomic writes, locks and read-only mappings |
| `std/fs/capability` | File access limited to a directory descriptor |
| `std/fs/watch` | File watching: inotify, kqueue or ReadDirectoryChangesW |
| `std/path` | Lexical slash-separated paths |
| `std/process` | Spawn, capture, pipes, environment and arguments |
| `std/process/signal` | Interrupt, terminate and hangup signals as queued events, read with `poll` or `wait` |
| `std/thread`, `std/sync` | Arena-backed thread handles; caller or owned stacks; portable synchronization |
| `std/thread/pool` | Fixed worker pool over a bounded arena queue, and wait groups |
| `std/time` | Monotonic and realtime clocks, durations, deadlines, calendar dates and UTC ISO-8601 |
| `std/time/zone` | Time zones from TZif files, POSIX rules or the Windows zone; local time, strftime-style formatting and RFC 3339 |
| `std/terminal` | Raw mode, terminal size and key decoding |
| `std/dynlib` | Dynamic library loading (on Linux, link libc explicitly) |
| `std/os/linux`, `macos`, `windows`, `wasi` | Platform services; prefer the portable packages above |
| `std/errors` | Portable error categories that accompany native codes |
| `std/c` | C ABI scalar aliases and C-string helpers |

### Networking and crypto

| Package | Purpose |
| --- | --- |
| `std/font`, `font/ui` | TrueType simple/composite rasterizer, atlas packing and software UI font adapters |
| `std/ui` | Immediate-mode buttons, checkboxes, integer sliders and arena-owned draw commands |
| `std/ui/software` | RGBA software rendering with caller-provided bitmap glyphs |
| `std/text/layout`, `std/ui/text` | Unicode line layout, Latin pair kerning and positioned UI glyphs |
| `std/embedded/uart`, `timer`, `interrupt` | Polling UART, CLINT/SysTick and bare-metal critical sections |
| `std/audio/wav` | PCM and IEEE floating-point WAVE decoding and encoding |
| `std/image/pnm` | Plain/binary PPM and PGM decoding and binary encoding |
| `std/encoding/protobuf`, `msgpack`, `cbor` | Borrowed streaming tokens and arena-owned wire encoders |
| `std/event` | Portable level-triggered readiness queues: epoll, kqueue and WSAPoll |
| `std/net` | IPv4, IPv6 and Unix streams, IPv4 UDP multicast, polling and event queues |
| `std/net/dns` | DNS queries into caller storage |
| `std/net/http`, `http/concurrent` | HTTP/1 client, server and router, and a worker-pool server |
| `std/net/websocket` | RFC 6455 handshake and frame codec |
| `std/net/url` | URL parsing and component encoding |
| `std/net/tls` | Verified TLS client and server through OpenSSL; link it explicitly |
| `std/crypto/sha2`, `sha512`, `hmac`, `kdf`, `password` | SHA-256/SHA-512, HMAC-SHA-256, HKDF and PBKDF2 |
| `std/crypto/aes`, `chacha20`, `aead` | Native AES-256-GCM and ChaCha20-Poly1305 |
| `std/crypto/aesgcm`, `chacha20poly1305`, `poly1305` | Native caller-storage AEAD and one-time authentication |
| `std/crypto/exchange`, `signature`, `x25519`, `ed25519`, `p256` | Native X25519, Ed25519 and deterministic ECDSA P-256 |
| `std/crypto/der`, `pem`, `certificate`, `x509` | Borrowed certificate envelopes and explicit native trust-path validation |
| `std/crypto/random` | OS entropy |

### Tooling

| Package | Purpose |
| --- | --- |
| `std/testing` | Expectations, benchmarks, temporary paths, property checks with shrinking, mutation fuzzing and structured fuzz input |
| `std/profile` | Monotonic spans recorded into caller storage |
| `std/observe` | Optional allocation-free event log used by arenas and other packages |
| `std/progress` | Nested progress counters in caller storage |
| `std/log` | Logging to an explicit writer |
| `std/debug` | Hex dumps |
| `std/reflect` | Categories over `#typeof` metadata |

## Platforms

Linux x86-64 has the broadest coverage, with Linux AArch64, macOS AArch64 and
Windows x86-64 close behind. Threads, sync, processes and file watching work on
all four, and so do `std/terminal` and `std/dynlib`. On Windows,
`std/terminal` uses console modes and `std/dynlib` reports `GetLastError`
codes instead of loader messages. On WASI, `std/terminal` reports
`Unsupported` and only `key_decode` is useful. On wasm32, see
[WebAssembly](webassembly.md). Packages gated to a platform say so with
`#target` at the top of their files.

## Vendor packages

Optional bindings to native libraries live under `vendor/`. Importing one adds
its native dependency, and each package documents its supported subset. See
[vendor packages](vendor.md).

## Math conventions

`std/math` uses concrete `Vec2`, `Vec3`, `Vec4` (f32) and `Vec2i` (i32)
structs. Functions use type prefixes such as `vec3_dot` and `vec3_normalize`.
Vector multiplication is componentwise; matrix multiplication composes
transforms. Finite vector normalization widens its intermediate arithmetic to
f64. Zero normalization returns a zero vector. Integer vector arithmetic is
checked, including intermediate dot products.

`Mat3` and `Mat4` store columns and multiply column vectors; the right operand
is applied first. Mat3 transforms are homogeneous 2D transforms. Rotations use
radians and a right-handed convention. Cameras look down −Z; projection depth
maps the near plane to −1 and the far plane to +1. Inverses and fallible
constructors return `{value, ok}`; failure has a zero value. Inversion uses
partial pivoting and does not guarantee a useful answer for ill-conditioned
matrices. Quaternions store `x, y, z, w`.

`Rng1u64`, `Rng1i64`, `Rng1f32`, `Rng2f32` and `Rng2i32` are half-open
ranges: `min` is included and `max` is excluded. Equal endpoints are empty;
rectangles are empty when either dimension is zero. Endpoints must be ordered
and must not be NaN. Overlap excludes touching edges. Union treats empty
ranges as identities. Range clamp uses the closed endpoint interval, so its
result can equal `max`. Integer centers round toward the lower endpoint;
integer dimensions and padding panic if their result cannot be represented.

The floating-point implementation has sampled host and RV32/Thumb execution
tests. It assumes round to
nearest, ties to even, and requires no host libm at runtime. Sampled comparisons
with host libm are not a global accuracy proof. Direct calls to trusted SDK math leaves use native instructions when the target permits them. Square root uses hardware FP on hard-float targets; copy-sign uses integer bits. AArch64 also lowers floor, ceil, truncation, ties-away rounding and fused FMA. RV32/RV64 and Thumb hard-float lower fused FMA. On x86, `--cpu native` enables SSE4.1 rounding and FMA only when CPU and OS support are present. Generic x86 and soft-float keep portable fallbacks where needed. Wasm lowers square root, floor, ceil, truncation and copy-sign; its nearest instruction does not implement ties-away round. Address-taken functions retain ordinary callable bodies.

### Multicast and local streams

`net.tcp_listen_ipv6` and `tcp_connect_ipv6` use the same owned `Listener`
and `Connection` handles as IPv4. `unix_listen` and `unix_connect` accept
`net.unix(path)`; empty, oversized and embedded-NUL paths are invalid. The
caller removes the filesystem socket path after closing its listener. Windows
requires OS support for AF_UNIX.

For IPv4 UDP multicast, call `multicast_join_ipv4` with network-order group
and interface octets; an all-zero interface selects the system default.
`multicast_interface_ipv4` selects the outgoing interface, `multicast_ttl_ipv4`
sets its TTL, and `multicast_leave_ipv4` drops membership. The loop option
controls outgoing loopback on POSIX and receipt on Windows, matching the native
socket semantics. Multicast delivery still depends on interface configuration.

### Readiness queues

`event.open(arena, capacity)` creates a single-owner, single-thread queue with
caller-owned registration storage. Add nonblocking socket descriptors with
`event.add(queue, descriptor, event.Readable | event.Writable, token)`, change
interests with `modify`, and remove them before closing or reusing descriptors.
The queue does not own registered sockets. Unix descriptors supported by the
native backend may also be registered; Windows accepts sockets only.

`event.wait(scratch, queue, milliseconds)` returns arena-owned events carrying
the descriptor, caller token, and readiness/error/hangup flags. Use a separate
scratch arena and rewind it between batches. Zero timeout polls; negative waits
indefinitely. Interrupted finite waits preserve the original deadline. Readiness
is level triggered and may become stale before an I/O call. macOS can return
separate read and write events for one descriptor. Native control failures
poison the queue because a multi-filter update can partially succeed: close and
rebuild it. Validation errors do not poison it. Close is idempotent.

Linux uses epoll, macOS uses kqueue, and Windows uses WSAPoll. Windows waits
scan the registered sockets; this is not an IOCP operation-completion API.
Timeouts let a caller run timers between batches; callbacks, timer scheduling,
GUI message pumping and cross-thread wakeups remain application responsibilities.

### Portable lanes

`std/simd` provides `U8x16`, `I8x16`, `U16x8`, `I16x8`, `U32x4`, `I32x4`,
`U64x2`, `I64x2`, `F32x4` and `F64x2`. Each is a 16-byte array alias with
ordinary element alignment and indexing. Functions use the lane type as a
prefix, for example `u32x4_add(a, b)`, `u32x4_splat(value)`, `u32x4_load(slice)`
and `u32x4_store(slice, value)`. Loads and stores require a full lane value's
worth of elements, panic on short slices, and leave any trailing elements alone.

Integer add, subtract and multiply wrap independently per element in every
build mode. Integer and/or/xor operate on bits. Equality returns all-one or
zero masks per element; select takes bits from its first input where the mask
is one and from its second input otherwise. Float add/subtract/multiply/divide
use ordinary scalar float semantics.

At O3, supported 32/64-bit integer add/subtract and bitwise loops use SSE2 on
x86-64 or NEON on ARM64. Other operations and targets retain scalar code;
float lanes do not currently promise hardware SIMD. These values are not native
vector ABI types and must not be passed to C functions expecting vector types.

### Immediate-mode UI

`std/ui` is a portable UI core with no window system or native library dependency.
Construct a `ui.Context{}` once, then call `begin`, submit widgets, and call `end`
for each frame. The application supplies integer rectangle bounds and stable,
nonzero widget IDs; IDs must be unique within a frame. `button`, `checkbox` and
`slider` return responses containing activation, focus, hover, capture and change
flags. Checkboxes and sliders update caller-owned values. Disabled widgets do
not accept input. Sliders normalize enabled values into the supplied inclusive
range, which must have distinct ordered endpoints.

`Input` contains pointer coordinates and the current left-button state. Press
and release edges are derived from consecutive frames; explicit `pressed` and
`released` fields also preserve a complete click arriving between frames.
Pointer capture persists while dragging, and release activates a button only
inside its visible rectangle. A release without capture does not activate it.
Tab advances focus in submission order, `activate` triggers a focused button or
checkbox, and `left`/`right` adjust a focused slider. Window hosts supply these
logical input events, including any desired keyboard repeat. Missing or disabled
widgets lose focus and capture. Overlapping widgets give pointer priority to the
first submitted widget. Submit non-overlapping controls when visual stacking
would otherwise imply a different order.

The frame arena owns command nodes and copies of label text. `first` and `next`
iterate the list until `Kind.None`; misses return `nil_command`. Render only
after `end` and before resetting the frame arena. Keep the context and application
state outside that arena. `begin` discards the old list. Building outside a frame,
starting a second frame, reading an unfinished list, or using ID zero panics in
both debug and release. `push_clip` returns the previous clip; pass it to
`pop_clip` to restore it. Each command snapshots its clip and color.

`std/ui/software` renders this list into caller-owned straight-alpha RGBA bytes.
A surface provides width, height and byte stride; its pixel slice must contain
all full row strides, including padding. The renderer clips to the surface and
the command bounds and performs source-over alpha blending. A caller-provided
`Font` callback returns alpha-coverage glyphs, offsets and advances for Unicode
code points. Invalid UTF-8 is replaced with U+FFFD. Glyph coverage may borrow
scratch storage until the next callback. Text supports newlines and clipping;
font loading, wrapping, kerning and shaping are separate work. Invalid surface,
font or glyph data returns `InvalidInput`; a glyph error can leave earlier draws
visible because rendering modifies the surface in place.

The [headless example](../../tests/ui-demo/main.dyn) demonstrates controls,
keyboard-capable state, bitmap text and PNG output. From the compiler directory:

```sh
build/dyn-release build tests/ui-demo --release --output build/ui-demo
(cd build && ./ui-demo)
```

The example writes `build/ui-demo.png`. Its small bitmap alphabet belongs to the
example; it is not a built-in std font. Native windows, OpenGL/Vulkan backends and general text layout remain planned.
TrueType font support is described below.

### TrueType fonts and atlases

`font.open(bytes)` reads one SFNT TrueType face. The returned face borrows the
bytes, which must remain immutable and alive. Unicode cmap formats 4 and 12,
short/long loca, horizontal metrics and simple/composite quadratic glyf outlines are
supported. `glyph_index` returns glyph zero on a miss. `raster(arena, face,
index, pixels_per_em)` produces an arena-owned alpha bitmap with horizontal
advance and baseline-relative offsets. It ignores hint instructions and uses
flattened quadratic curves with nonzero winding and 4x4 supersampling.

Composite glyphs support signed byte/word XY offsets, contour-point attachment,
uniform and independent-axis scale, full 2x2 transforms, nested components, and
component-selected horizontal metrics. Unspecified or conflicting offset-scaling
flags use the OpenType-recommended unscaled default. Hint programs and grid-fit
rounding are ignored. Phantom-point attachment returns `Unsupported`.
Component-selected metrics require a diagonal transform with nonnegative
horizontal scale; other transforms return `Unsupported` rather than an approximation. Cyclic graphs,
invalid component indices, contradictory transform flags and truncated records
return `InvalidInput`. Other OpenType features—collections, CFF, variable-instance
selection, hinting and complex-script shaping—remain unimplemented. Legacy horizontal
`kern` format 0 pair adjustments and Latin text layout are provided separately. A face can open successfully while an individual glyph returns `Unsupported` or
`InvalidInput`. Structural checks are not a complete font-conformance validator;
checksums are not verified. Parse errors use portable `kind`, native `error`
(zero for parser failures), and `offset` when known. Failed raster/atlas calls
rewind their arena allocations.

Rasterization accepts 1..256 pixels per em. Limits are 8,192 total leaf outline
points, 256 glyph nodes per expansion, 16 active glyph levels, transformed
coordinates/selected metrics within 1,048,576 design units in magnitude,
1,048,576 bitmap pixels, 4,096 per dimension, and 16,777,216 pixel-edge pairs
before supersampling. Larger work returns `Capacity`. Temporary storage includes
points, flags, accumulated component copies and up to 129 edges per point; it is
rewound before returning. Output reserves at most one extra row/column around
the initial bounds to allow component-selected metric origins to change fractional
pixel alignment; the returned slice contains only the actual bitmap pixels.
This CPU reference renderer favors portability and bounded storage over speed.

`font.atlas(arena, face, codepoints, pixels_per_em, width, height)` shelf-packs
coverage into a caller-sized atlas with transparent padding. Codepoints must be
strictly increasing Unicode scalars; dimensions are 1..4096. The atlas also
caches glyph zero for lookup misses. `atlas_glyph` performs binary lookup and
returns that fallback, or `nil_glyph` for an empty atlas. Atlas bytes and glyph
records belong to the output arena. Cached output does not borrow font bytes.

`font/ui.atlas_renderer(atlas)` adapts a stable atlas descriptor to the software
renderer without allocation or rasterization. The direct `Adapter` alternative
rasterizes on demand into its caller arena and keeps a sticky failure category;
the software renderer returns `InvalidInput` for that failed callback. Both use
hhea ascent/descent/line gap for baseline placement and newline spacing. Glyph
coverage permits unused padding after the last row to be omitted, so atlas
subregions do not require copied buffers.

The [TrueType UI example](../../tests/font-ui-demo/main.dyn) accepts a font and
output path. Font data is not bundled:

```sh
build/dyn-release build tests/font-ui-demo --release --output build/font-ui-demo
build/font-ui-demo /path/to/font.ttf build/font-ui-demo.png
```

The reader follows the OpenType [glyf](https://learn.microsoft.com/en-us/typography/opentype/spec/glyf),
[cmap](https://learn.microsoft.com/en-us/typography/opentype/spec/cmap),
[head](https://learn.microsoft.com/en-us/typography/opentype/spec/head),
[hhea](https://learn.microsoft.com/en-us/typography/opentype/spec/hhea) and
[hmtx](https://learn.microsoft.com/en-us/typography/opentype/spec/hmtx) specifications.


### Text layout and embedded helpers

`text/layout.build(arena, source, font, options)` owns a text copy, positioned
glyphs and line records. NFC normalization is enabled by default; glyph/line byte
offsets refer to the returned text, not the original source. Layout preserves
grapheme clusters, uses Unicode line-break opportunities, handles mandatory
breaks, tabs and conditional soft hyphens, and supports left/center/right alignment.
Oversized words use emergency wrapping. Combining marks have zero advance; bidi,
GSUB/GPOS and complex-script shaping are not implemented. `font/ui.LayoutAdapter`
provides atlas advances and legacy TrueType pair kerning. `ui/text.label` snapshots
positioned glyph commands into the UI frame arena.

Embedded UART descriptors provide caller-selected register addresses, access
width and readiness polarity, including NS16550 and CMSDK defaults. Writes poll
without a timeout. The timer package provides coherent CLINT reads and safe split
compare writes, and SysTick periods from 2 through 2^24 ticks. CLINT helpers require
strongly ordered little-endian device I/O; they do not configure memory attributes.
Interrupt helpers preserve nested RISC-V MIE or Thumb PRIMASK state. Vector checks
validate only architectural minimum alignment; the board must enforce any larger
alignment required by its vector table. Thumb also exposes NVIC operations.

### Portable media and wire formats

`audio/wav.decode` returns owned interleaved f32 samples from PCM8/16/24/32 and
IEEE32/64 WAVE, including extensible PCM/IEEE headers. Encoding supports PCM8/16/24/32
and IEEE32, writing channel masks and float fact chunks when needed. Integer output
clamps and rounds finite samples; IEEE32 preserves raw floating-point bits. RF64,
RIFX and compressed formats return `Unsupported`.

`image/pnm.decode` reads P2/P3/P5/P6, scales 1..65535 sample ranges to 8-bit Gray/RGB,
and reports consumed bytes for concatenated raw images. Binary headers consume
exactly one raster delimiter: later whitespace and `#` bytes are pixels. Encoding
writes P5/P6 with Maxval 255. Transfer functions are preserved without conversion.

The protobuf, MessagePack and CBOR readers borrow their source and token payloads.
Their encoders own output in the supplied arena. Input must remain alive and must
not borrow unused output-arena storage. Parse errors are sticky and include byte
offsets; encoding errors use token indexes. Nesting is bounded to 64 active frames.
Protobuf emits explicit group fields and supports fixed/varint/length-delimited
fields plus ZigZag helpers; schemas and generated code are outside this module.
MessagePack emits preorder tokens with array/map counts and opaque extensions,
including timestamps; text payloads preserve invalid UTF-8 bytes. CBOR emits End
only for indefinite containers/strings, validates UTF-8 and chunk structure, wraps
one child per tag, and preserves its full negative-integer range as -1-n. Tag
semantics and duplicate-key policy belong to the caller. Neither codec promises
a canonical serialization profile. Multiple top-level values are supported.

The additional image decoders return arena-owned RGBA8 pixels and cap images at
16,777,216 pixels. BMP supports known Windows DIB headers, indexed 1/4/8-bit,
16/24/32-bit and contiguous bitfields; RLE and OS/2 headers are unsupported. TGA
supports true-color/gray, RLE and all origins, but omits color maps, 15/16-bit true
color and interleaving. GIF returns the first composited image with transparency
and interlace; later animation timing/disposal is not processed. JPEG supports
8-bit baseline sequential Huffman gray/RGB/YCbCr, interleaved/separate scans and
restart markers, with nearest chroma upsampling and a portable reference IDCT.
Progressive, arithmetic, lossless and CMYK JPEG are unsupported. Decode failures
rewind arena allocations; inputs must not borrow unused output-arena backing.

`encoding/toml.parse` owns all keys, strings and scalar lexemes. `member` and
`index` return `nil_value` on misses. Parsing covers TOML 1.0 table/array-of-table
rules, dotted/quoted keys, all four string forms, arrays, inline tables, signed
64-bit integer syntax, floats and date/time syntax, with 64-level nesting.
Scalar lexemes preserve precision, leap seconds and year 0000 without requiring
conversion to a platform datetime. The normalized writer uses quoted keys and
inline tables and preserves scalar spelling. Failed parse/write calls rewind;
manual malformed or cyclic/deep trees are rejected. Neither input nor tree storage
may borrow unused output-arena backing.


### Native authenticated encryption

`crypto/aead` and its AES adapter use native Dyn implementations without OpenSSL.
The existing arena, alias-rejection, rollback and failure-zeroing contracts remain.
Key size is 32 bytes; tags are 16 bytes; ChaCha nonces are 12 bytes and AES-GCM
nonces are 1..128 bytes. The facade preserves the existing INT_MAX payload/AAD
limits. `provider_code` remains for source compatibility and is always zero.

The lower-level `aesgcm.seal/open` and `chacha20poly1305.seal/open` write exact-sized
caller storage and allow exact in-place payload operation. Partial overlap and
output overlap with other inputs are rejected. Authentication is checked before
decryption; failed operations preserve caller output. Nonce uniqueness is the
caller's responsibility. `poly1305` keys are one-time keys and must never be reused.

AES uses a table-free finite-field S-box and fixed-iteration GHASH, favoring
portability over throughput. Poly1305 uses bounded five-limb arithmetic. Source
avoids secret indexes and secret branches, but that does not establish machine
constant-time behavior on every target. Selected O2/O3 mask and comparison
sites are inspected on x86-64, AArch64 and RISC-V. Full scope and limitations are
recorded in the [crypto review](../internals/native-crypto-review.md). State clearing
is not a guarantee that optimized code erases every stack/register copy.


### Native signatures and trust paths

X25519 and Ed25519 now use native fixed-limb arithmetic. X25519 rejects all-zero
shared secrets. Ed25519 verifies canonical encodings and scalars, nonidentity
prime-subgroup public keys, and signature equations. SHA-512 is a native streaming
implementation. P-256 uses uncompressed SEC1 65-byte public keys and raw 64-byte
r||s signatures; message APIs use SHA-256, with separate digest APIs in `p256`.
Signing uses deterministic RFC 6979 and does not normalize to low-S. The existing
`exchange` and `signature` result/tail/overlap contracts remain; `signature` also
exposes `p256_public`, `p256_sign` and `p256_verify`. Provider diagnostics are zero.

`x509.inspect` borrows strict DER fields and validates supported public keys.
`x509.validate` takes a leaf-first ordered chain, explicit DER anchors and caller
Unix time, DNS name or raw IP, and optional server/client purpose. It verifies
Ed25519/ECDSA-SHA256 signatures, inclusive validity times, SAN identity, basic
constraints, path lengths, key usage and extended key usage. DNS matching uses
ASCII/A-labels, one complete leftmost wildcard label, and no CN fallback. IP
references use `options.ip`, not numeric DNS names. Issuer/subject names match
exact DER; normalized directory-name comparison is not implemented. Chain depth
is limited to 16. Exact terminal-anchor matches also permit direct leaf pins.

This is a restricted explicit-path validator, not complete browser PKIX policy:
RSA/other curves, name/policy constraints and unsupported critical extensions
fail closed. Unsupported constructed SAN forms and legacy Teletex names are
rejected. Path discovery, system trust stores, AIA fetching, revocation, IDNA
conversion and public-suffix policy remain caller responsibilities. External
anchors are explicit trust policy; chain entries are time-checked. Native TLS
continues to use its separate OpenSSL provider; these modules do not replace
TLS handshake or trust-store behavior.

HKDF expansion and PBKDF2 require destination/scratch to be disjoint from each
other and borrowed inputs, including provided slice tails. Invalid lengths and
aliases are rejected before writes. HMAC itself permits destination overlap with
inputs because it consumes inputs before emitting the digest; oversized inputs
return an empty slice. These contracts prevent key corruption across KDF blocks.

### Vendor graphics and fonts

Native windows and UI backends are in `vendor/window` and `vendor/ui/opengl` or
`vendor/ui/vulkan`; see their READMEs for native bridge builds and ownership.
The OpenGL path presents native windows; Vulkan currently renders offscreen via
compute and copies completed RGBA pixels to caller storage. FreeType and HarfBuzz
provide dynamic native font/raster/shaping tables; HarfBuzz copies shaped glyph
records into caller arenas, and the FreeType adapter supports Unicode or shaped
glyph IDs. Complex-script run shaping is distinct from paragraph bidi, fallback
and line layout, which remain application policy.
