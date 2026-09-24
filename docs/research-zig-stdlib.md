# Zig stdlib lessons for Dyn

Research date: 2026-09-15. Sources are Zig's official `master` documentation and repository. Zig
`master` is moving toward 0.17, so this is design input, not an API compatibility target.

## Answer

Yes. Dyn's v2 map already covers most application-facing Zig batteries. Best additions exposed by
comparison are small operational modules and deeper behavior inside planned modules—not copying
Zig's whole package tree.

### Add to Dyn's design

1. **`semver`** — parse, compare, format, and later ranges. Package manifests, protocol negotiation,
   update tools, and vendor-version checks all need this. Zig gives semantic versions a first-class
   type with parsing, ordering, formatting, and a `Range` type
   ([source](https://github.com/ziglang/zig/blob/master/lib/std/SemanticVersion.zig)). Dyn's shipped
   std and v2 map have no equivalent.

2. **`progress`** — non-allocating nested progress reporting with serialized stderr access. This is
   disproportionately useful for compilers, package tools, archive tools, and long CLI jobs. Zig's
   implementation explicitly targets non-allocation, non-failure, thread safety, and lock freedom,
   and exposes progress nodes plus stderr coordination
   ([source](https://github.com/ziglang/zig/blob/master/lib/std/Progress.zig)). Put this beside
   `term`, not inside logging.

3. **`debug` diagnostics** — panic/assert policy, stack capture, symbolized stack rendering where
   supported, hex dumps, and crash-handler integration. Zig treats these as a coherent facility and
   separates platform/debug-format machinery behind it
   ([source](https://github.com/ziglang/zig/blob/master/lib/std/debug.zig)). Dyn currently has an
   assert primitive and planned profiling, but neither replaces post-crash diagnostics. Keep binary
   symbol readers internal until external tooling needs them.

4. **Application-directory discovery in `fs`/`os`** — cache, config, data, runtime, and executable
   locations using host conventions. Zig includes `fs.getAppDataDir` and `selfExePath`
   ([filesystem source](https://github.com/ziglang/zig/blob/master/lib/std/fs.zig)). Dyn should use
   caller storage or arena-returning variants; avoid hidden allocation.

5. **Atomic file replacement as a named workflow** — temporary sibling, write/sync as requested,
   rename/commit, cleanup on failure. Zig promotes `AtomicFile` as a filesystem type
   ([source](https://github.com/ziglang/zig/blob/master/lib/std/fs/AtomicFile.zig)). Dyn's planned
   `fs` breadth should name this explicitly because config files, package metadata, and caches need
   correct policy rather than repeated syscall recipes.

6. **More complete crypto taxonomy** — v2 currently names AES, HMAC, random, and SHA-2, but serious
   batteries also need authenticated encryption, signatures, key exchange, key derivation/password
   hashing, secure zeroing, timing-safe comparison, certificate parsing, and PEM/DER codecs. Zig's
   official crypto root groups AEAD, authentication, DH, KEM, ECC, hashes, KDFs, password hashing,
   signatures, stream ciphers, TLS/certificates, `secureZero`, and timing-safe operations
   ([source](https://github.com/ziglang/zig/blob/master/lib/std/crypto.zig)). Dyn may provider-back
   these; stable public algorithms must be curated and audited.

7. **Explicit bounded utility structures** — static/dynamic bit sets, deque/ring, priority queue,
   enum-indexed sets/maps, intrusive lists, and fixed string lookup. Zig's public root exposes these
   alongside its maps and lists
   ([source](https://github.com/ziglang/zig/blob/master/lib/std/std.zig)). Dyn v2 mentions bit sets
   and rings but should record priority queue and intrusive list as desired capabilities. Public
   typed versions remain blocked on Dyn's collection/generics decision.

8. **Full numeric/binary primitives** — fixed-endian reads/writes, checked arithmetic, float
   classification/decomposition, and signed/unsigned LEB128. Zig exposes a dedicated LEB128 module
   and broad scalar math surface
   ([stdlib root](https://github.com/ziglang/zig/blob/master/lib/std/std.zig),
   [math source](https://github.com/ziglang/zig/blob/master/lib/std/math.zig)). Dyn already ships a
   varint and endian helpers; move and test them under `encoding/binary` rather than inventing new
   top-level packages. Big integers should enter only after compiler, crypto, or user workloads prove
   need.

9. **HTTP parser policy, not merely client/server labels** — request/status enums, bounded header
   parsing, chunk framing, body streaming, content decoding, and explicit size limits. Zig exposes
   separate head/chunk parsers plus client/server and body reader/writer machinery
   ([source](https://github.com/ziglang/zig/blob/master/lib/std/http.zig)). This supports Dyn's planned
   `net/http`; use it as a completeness checklist, not an interface template.

10. **Compression beyond zstd/gzip only when workloads demand it** — Zig includes DEFLATE, LZMA,
    LZMA2, XZ, and zstd
    ([source](https://github.com/ziglang/zig/blob/master/lib/std/compress.zig)). Dyn should guarantee
    deflate/gzip/zstd first. XZ/LZMA are useful for package/archive tooling but lower priority and can
    begin under `vendor` if provider-backed.

11. **Host/target facts as stable data** — architecture, OS, ABI, endianness, page-size bounds, CPU
    features, executable/object format, and capability checks. Zig exposes compile variables through
    the compiler-provided `builtin` package
    ([language documentation](https://ziglang.org/documentation/master/#Compile-Variables)). Dyn's
    planned `os` platform facts should distinguish compile target from machine currently running the
    compiler.

## Already covered; deepen rather than add names

- Zig's main public root includes filesystems, URI, HTTP, JSON, compression, crypto, archive formats,
  time zones, process control, threading, dynamic libraries, logging, testing, and collections
  ([official root](https://github.com/ziglang/zig/blob/master/lib/std/std.zig)). Dyn's v2 map already
  has equivalents for nearly all application-facing areas.
- Zig's HTTP surface has both `Client` and `Server`, while Dyn already plans both. Focus on limits,
  timeouts, redirects, proxy behavior, streaming, TLS roots, and malformed input rather than another
  package split ([source](https://github.com/ziglang/zig/blob/master/lib/std/http.zig)).
- Zig's process module covers argument iteration, environment maps, current directory, user data,
  spawning/exec, and system memory queries
  ([source](https://github.com/ziglang/zig/blob/master/lib/std/process.zig)). Dyn already plans these
  categories; portability and ergonomic child-process capture are missing depth.
- Time-zone support is worth retaining in v2: Zig exposes `Tz` separately from base time operations
  ([official root](https://github.com/ziglang/zig/blob/master/lib/std/std.zig)). Shipping/update policy
  for zone data still belongs outside core runtime.

## Zig-specific ideas Dyn should reject or defer

1. **Do not copy Zig's generic allocator as universal parameter.** Zig containers and APIs are built
   around `mem.Allocator`; its interface includes allocate, resize, remap, and free operations
   ([source](https://github.com/ziglang/zig/blob/master/lib/std/mem/Allocator.zig)). Dyn's arena-first
   design communicates lifetime and bulk invalidation better. Keep arenas/caller buffers primary;
   add richer allocator/heap seam only after real independent-reclamation workloads demand it.

2. **Do not copy managed/unmanaged container duplication.** Zig publicly exposes paired hash maps,
   array hash maps, and bit sets, plus allocator-taking collection variants
   ([official root](https://github.com/ziglang/zig/blob/master/lib/std/std.zig)). This fits Zig's generic
   allocator model but would multiply Dyn APIs before Dyn has generics. Prefer one storage-explicit
   convention.

3. **Do not copy Zig's current wide `Io` execution context.** Zig `master`'s `Io` includes a vtable,
   async futures/groups/select, cancellation, clocks, synchronization, queues, networking, files,
   and threaded/evented backends
   ([source](https://github.com/ziglang/zig/blob/master/lib/std/Io.zig)). Dyn's two-word, one-operation
   `Reader`/`Writer` seams are easier to reason about. Add cancellation/deadlines as explicit values;
   do not make every ordinary I/O call depend on a universal runtime interface.

4. **Do not put compiler/build internals into stable application std.** Zig exports `Build`, target
   machinery, object/debug-format parsers (COFF, ELF, Mach-O, PDB, DWARF), WebAssembly definitions,
   and Zig compiler internals from its root
   ([official root](https://github.com/ziglang/zig/blob/master/lib/std/std.zig)). These serve Zig's
   self-hosting/toolchain goals. Dyn should place equivalents in compiler-internal or official
   tooling packages unless ordinary applications demonstrate demand.

5. **Do not copy root-global std configuration.** Zig lets a root file override global log behavior,
   crypto seeding, HTTP TLS behavior, page-size queries, and stack tracing through `std_options`
   ([source](https://github.com/ziglang/zig/blob/master/lib/std/std.zig)). Dyn philosophy favors
   explicit writers, contexts, providers, and options at construction/call sites. Compile-time global
   policy creates invisible coupling.

6. **Do not promise every algorithm Zig happens to ship.** Object readers, Valgrind hooks, GPU
   declarations, compiler AST/ZIR machinery, and niche containers are not evidence of universal app
   need. Inclusion still requires two real Dyn applications, coherent ownership, portable behavior,
   and maintenance capacity.

## Recommended patch to v2 package map

```text
std/
  semver              semantic-version parse/order/format/ranges
  debug               panic/assert, stack traces, crash diagnostics, hex dump
  progress            nested terminal progress, explicit output coordination
```

Also amend existing module requirements:

- `fs`: app directories and atomic replacement;
- `encoding/binary`: endian scalars plus signed/unsigned varints/LEB128;
- `crypto`: AEAD, timing-safe compare, secure zero, KDF/password hashing, signatures/key exchange,
  certificate and PEM/DER support;
- collections plan: priority queue and intrusive lists after typed-storage story exists;
- `net/http`: bounded header/chunk parsers and streaming content decoding;
- `os`: distinguish build target facts from host runtime facts.

Highest-value Zig borrow: operational polish (`debug`, `progress`, `semver`, atomic files). Biggest
mistake to borrow: Zig-wide allocator + universal I/O architecture.
