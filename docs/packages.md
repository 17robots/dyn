# Standard-library package reference

All packages are ordinary Dyn. Dyn-owned heap allocation requires explicit arena
ownership; caller buffers may be stack-backed. Returned slices borrow their
specified input/buffer/arena lifetime. Foreign providers own their own handles.

| Package | Role | Storage/error convention |
|---|---|---|
| `std/c` | target C scalar aliases and C-string boundary helpers | caller buffer; explicit foreign ownership |
| `std/flags` | options, flags, subcommands, positionals | definitions borrowed; results in caller slices; parse result struct |
| `std/compress/deflate`, `std/compress/gzip` | streaming stored, fixed, or deterministic dynamic-Huffman LZ77 DEFLATE encoding; complete DEFLATE and verified gzip decoding | caller output/hash buffers; result reports consumed/written bytes |
| `std/crypto/sha2`, `std/crypto/hmac`, `std/crypto/random` | one-shot/incremental SHA-256, HMAC-SHA-256, constant-time equality, secure OS entropy | caller state/buffers; Linux `getrandom` for entropy |
| `std/dynlib` | POSIX dynamic-library loading and symbol lookup | explicit close; borrowed symbols/errors; explicit libc link |
| `std/fmt` | construct textual values | caller `fmt.Buffer`; empty/false or count indicates capacity failure |
| `std/io` | borrowed Reader/Writer callbacks and stream operations | caller buffers; `{transferred,error,status}` for stream progress |
| `std/encoding/json` | validate, parse DOM, query, and write JSON | source borrowed; decoded nodes in caller arena; offset-bearing result |
| `std/math` | scalar numeric helpers | pure values; no storage |
| `std/sort` | in-place integer sorting and binary search | caller slices; no storage |
| `vendor/sqlite` | SQLite open, execute, errors, and close | explicit provider ownership; caller C-string storage; explicit SQLite link |
| `vendor/sdl3` | optional window, renderer, input, queued audio, and GPU swapchain lifecycle | SDL-owned handles; explicit destruction/linking; caller buffers |
| `std/mem` | heap/buffer-backed fixed arenas, growing arenas, scratch, pools and free lists | caller storage or explicit mapping; `try_`/panic pairs |
| `std/net` | IPv4/IPv6/Unix sockets, poll, DNS, HTTP/1, and stateful WebSocket codecs | caller packet/result buffers; native error result structs |
| `std/os` | target selection; platform-specific OS services | caller arenas/buffers; native error result structs |
| `std/profile` | bounded monotonic span recording | caller event slice; borrowed names; dropped count on capacity failure |
| `std/text/regex` | byte-pattern search plus caller-storage Thompson compilation, nested groups, captures, anchors, repetition, alternation, escapes, classes/ranges, and iteration | input/program/captures borrowed; `CompileError` distinguishes syntax/capacity; no hidden allocation |
| `std/reflect` | broad categories over `TypeInfo` | static compiler metadata; no allocation |
| `std/strings` | byte-string search, parse, scanning, glob, ASCII, UTF-8 | scanner/views borrow input; construction uses caller storage |
| `std/terminal` | standard streams and procedural logging | formats through stack/caller storage; returns write status |
| `std/testing` | assertions and temporary-resource helpers | panic on failed expectation; paths in caller storage |
| `std/thread` | caller-stack threads; synchronization in `std/sync` | caller-owned stacks/state; Linux x86-64 and AArch64 |
| `std/time` | monotonic/realtime clocks, checked durations, deadlines, UTC ISO-8601 | value result; direct syscall; timezone database intentionally external |
| `std/rand` | deterministic caller-owned PRNG and OS entropy | explicit state/buffer; not cryptographic |
| `std/net/url` | allocation-free URL decomposition | returned slices borrow input; offset-bearing parse result |
| `std/archive/tar` | ustar/PAX/GNU metadata and streaming entry iteration | returned slices borrow archive; caller-owned cursor |
| `std/net/tls` | verified client and certificate-backed server TLS through OpenSSL | explicit provider ownership; caller byte/name buffers; explicit provider linking |

Current platform and protocol limits are documented in [release formats](release/formats.md). Package source is
the API source of truth; the [generated SDK reference](reference/README.md) indexes
public declarations, contracts and example fixtures.

`std/fs` owns file/directory operations, `std/path` lexical path operations,
`std/terminal` terminal control, and `std/os/linux` Linux process/environment
services. `std/bufio` buffers the `std/io` callback interface. `std/log` writes
through an explicit writer. Endian operations live in `std/encoding/binary`.
Fixed and growing arenas, scratch scopes, pools and free lists all live in
`std/mem`. Fixed arenas never implicitly grow.

Typed collection modules (`std/container/bit_set`, `ring`, and `slot_map`) retain
caller storage. `std/container/string_map` and
`std/bytes/builder` support explicit arena growth; see [collections](collections.md).
Generic containers and compiler-internal storage are outside the SDK release scope.

`std/testing.temporary_path` generates a candidate name into caller storage; it
does not reserve a file. Expected-panic tests use subprocesses.

## Additional optional providers

New bindings cover Tree-sitter, PCRE2, Lua 5.4, libarchive, libcurl, SDL_image 3,
SDL_ttf 3 and context-loaded OpenGL. See [native-provider setup and contracts](vendor-additions.md)
for dependency versions, supported subsets, ownership and runnable examples.

Additional optional providers include SDL_mixer, cgltf, Box2D, microui, LZ4, ENet
and miniaudio. [Package contracts and native build setup](vendor-game-libs.md)
describe the tested subsets and memory lifetimes.

Atlas packing and resizing are available under `vendor/stb/rect_pack` and
`vendor/stb/image_resize`. `vendor/sdl3/microui` supplies the optional SDL UI backend.
See [vendor workflow examples and limits](vendor-game-libs.md).
