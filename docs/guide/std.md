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
- **Zero is initialization.** A zeroed data struct is a valid empty value: `Builder{}`,
  `process.Options{}` (inherit every stream), and scanners given only their
  `source`. Arena handles are pointers to backing headers and require
  `arena_create` or `arena_from_buffer`; a nil arena handle does not allocate.
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
| `std/fmt` | Formatting into a bounded caller buffer |
| `std/unicode/utf8`, `utf16`, `text` | Strict UTF-8 and UTF-16, case folding and normalization |
| `std/text/scanner` | Line and field scanner with positions |
| `std/text/regex` | Thompson-NFA regular expressions compiled into an arena; reusable workspace |
| `std/text/template`, `std/html/template` | Text templates, and HTML templates that escape text and quoted attributes |
| `std/container/list` | Intrusive stacks, queues, doubly linked lists, trees and free lists |
| `std/container/hash` | Intrusive chained hash tables and seeded SipHash-1-3 |
| `std/container/chunk` | Chunk lists that grow on a shared arena without copying |
| `std/container/slot_map` | Generation handles into caller slot arrays |
| `std/container/ring`, `bit_set` | Ring buffer and bit set over caller storage |
| `std/sort` | In-place sort and binary search for any ordered element type |
| `std/math` | Scalar arithmetic, bit helpers, concrete vectors, matrices, quaternions and ranges |
| `std/hash` | Stable non-cryptographic hashes (FNV-1a) and checksums |
| `std/rand` | Deterministic caller-owned PRNG; not for cryptography |

### Encoding and formats

| Package | Purpose |
| --- | --- |
| `std/encoding/json` | Validation, arena-backed mutable DOM parsing, queries and writing |
| `std/encoding/json/read` | [Experimental compact read-only DOM](json-read.md), with arena-owned values and text |
| `std/encoding/csv` | RFC 4180 field scanner, stream scanner and writer |
| `std/encoding/ini` | INI scanner and one-pass `parse` into an arena table |
| `std/encoding/xml` | XML document trees, event scanner, attributes, namespaces and writer |
| `std/encoding/mdesk` | Metadesk-style labeled trees with tags |
| `std/encoding/hex`, `base32`, `base64` | Codecs into caller buffers that validate before writing |
| `std/encoding/binary` | Fixed-width endian and unsigned LEB128 encoding |
| `std/semver` | Semantic Versioning 2.0 values |
| `std/compress/deflate`, `gzip`, `zstd` | DEFLATE encode and decode, gzip members, zstd compress and decompress |
| `std/archive/tar`, `zip` | TAR (ustar, PAX, GNU) and ZIP reading |
| `std/image/png`, `qoi`, `color` | PNG encode and decode, QOI decode, into caller RGBA storage |

### Operating system

| Package | Purpose |
| --- | --- |
| `std/io` | `Reader`/`Writer` callbacks, standard streams and `print`/`println` |
| `std/bufio` | Buffered readers and writers over caller storage |
| `std/fs` | Files, directories, metadata, atomic writes and locks |
| `std/fs/capability` | File access limited to a directory descriptor |
| `std/fs/watch` | File watching: inotify, kqueue or ReadDirectoryChangesW |
| `std/path` | Lexical slash-separated paths |
| `std/process` | Spawn, capture, pipes, environment and arguments |
| `std/thread`, `std/sync` | Arena-backed thread handles; caller or owned stacks; portable synchronization |
| `std/time` | Monotonic and realtime clocks, durations, deadlines and UTC ISO-8601 |
| `std/terminal` | Raw mode, terminal control and key decoding (Linux) |
| `std/dynlib` | Dynamic library loading (Linux; link libc explicitly) |
| `std/os/linux`, `macos`, `windows`, `wasi` | Platform services; prefer the portable packages above |
| `std/errors` | Portable error categories that accompany native codes |
| `std/c` | C ABI scalar aliases and C-string helpers |

### Networking and crypto

| Package | Purpose |
| --- | --- |
| `std/net` | IPv4, IPv6 and Unix sockets, polling and event queues |
| `std/net/dns` | DNS queries into caller storage |
| `std/net/http`, `http/concurrent` | HTTP/1 client, server and router, and a worker-pool server |
| `std/net/websocket` | RFC 6455 handshake and frame codec |
| `std/net/url` | URL parsing and component encoding |
| `std/net/tls` | Verified TLS client and server through OpenSSL; link it explicitly |
| `std/crypto/sha2`, `hmac`, `kdf`, `password` | SHA-256, HMAC-SHA-256, HKDF and PBKDF2 |
| `std/crypto/aes`, `chacha20`, `aead` | Ciphers and authenticated encryption |
| `std/crypto/exchange`, `signature` | X25519 and Ed25519 |
| `std/crypto/der`, `pem`, `certificate` | Certificate parsing; trust decisions stay with TLS |
| `std/crypto/random` | OS entropy |

### Tooling

| Package | Purpose |
| --- | --- |
| `std/testing` | Expectations, benchmarks and temporary paths |
| `std/profile` | Monotonic spans recorded into caller storage |
| `std/observe` | Optional allocation-free event log used by arenas and other packages |
| `std/progress` | Nested progress counters in caller storage |
| `std/log` | Logging to an explicit writer |
| `std/debug` | Hex dumps |
| `std/reflect` | Categories over `#typeof` metadata |

## Platforms

Linux x86-64 has the broadest coverage, with Linux AArch64, macOS AArch64 and
Windows x86-64 close behind. Threads, sync, processes and file watching work on
all four. `std/terminal` and `std/dynlib` are Linux only. On wasm32, see
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
