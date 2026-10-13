# Standard library

Every std package is ordinary Dyn source shipped with the SDK. The source is the
API reference: `dyn docs std/strings` prints a module's public declarations and
their contracts, and `dyn docs std/strings --json` gives the same as JSON.

## Conventions

- **No hidden allocation.** A function that needs memory takes a `*mem.Arena`
  or a caller slice. Arena pushes cannot fail; caller-slice functions report
  `Capacity` with the exact size `required`. See [memory](memory.md) and
  [buffer contracts](buffer-contracts.md).
- **Borrowing is the default.** Returned slices borrow the input, the caller's
  buffer or the arena, as each function's comment says. Reader-backed scanners
  return views that last until the next call.
- **Zero is initialization.** A zeroed struct is a valid empty value: `Arena{}`,
  `Builder{}`, `Map{}`, `GrowingArena{}`, scanners given only their `source`.
  Constructors exist for convenience, not because zero is broken. The exception
  is `process.Options`, where 0 is a real file descriptor; use
  `process.options()`.
- **Errors are values.** OS calls return `{value, error, kind, ok}`: `error`
  keeps the native code and `kind` is a portable `std/errors` category.
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
| `std/mem` | Arenas, typed pushes, scratch scopes, frames, growing arenas, pools and free lists |
| `std/bytes` | Byte-slice operations, cursors and splitters |
| `std/bytes/builder` | Byte and UTF-8 string builder over caller storage or an arena |
| `std/bytes/search` | Prepared KMP search |
| `std/strings` | Search, parse, split, join, format, glob, ASCII helpers and string lists |
| `std/fmt` | Formatting into a bounded caller buffer |
| `std/unicode/utf8`, `utf16`, `text` | Strict UTF-8 and UTF-16, case folding and normalization |
| `std/text/scanner` | Line and field scanner with positions |
| `std/text/regex` | Thompson-NFA regular expressions compiled into caller storage |
| `std/text/template`, `std/html/template` | Text templates, and HTML templates that escape text and quoted attributes |
| `std/container/string_map` | Open-addressing map from byte strings to `usize` |
| `std/container/slot_map` | Generation-checked handles to fixed-size records |
| `std/container/ring`, `bit_set` | Ring buffer and bit set over caller storage |
| `std/sort` | In-place sort and binary search for any ordered element type |
| `std/math` | `min`, `max`, `clamp`, `abs`, `narrow` and other scalar helpers |
| `std/hash` | Stable non-cryptographic hashes (FNV-1a) and checksums |
| `std/rand` | Deterministic caller-owned PRNG; not for cryptography |

### Encoding and formats

| Package | Purpose |
| --- | --- |
| `std/encoding/json` | Validation, arena-backed DOM parsing, queries and writing |
| `std/encoding/csv` | RFC 4180 field scanner, stream scanner and writer |
| `std/encoding/ini` | INI scanner and one-pass `parse` into an arena table |
| `std/encoding/xml` | XML event scanner, attributes, namespaces and writer |
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
| `std/thread`, `std/sync` | Caller-stack threads; mutexes, conditions, semaphores, once and atomics |
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
