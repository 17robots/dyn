# Standard library v2 design

Status: historical design proposal, not the current API specification. Shipped modules
live in `compiler/std/` and `compiler/vendor/`; names below may describe unimplemented
proposals. See [library contracts and migrations](library-migrations.md), [memory](memory.md),
and [TLS](tls.md) for current ownership and interface contracts.

## Goal

Dyn should ship enough coherent, portable modules to build command-line tools, servers, desktop
programs, data tools, and language tooling without beginning every project with dependency
selection. "Batteries included" means common policy and hard algorithms are present, not that every
foreign library binding belongs in `std`.

Every module keeps Dyn's existing invariants:

- allocation and retention are visible at the call site;
- arenas are the default storage model;
- borrowed data stays borrowed and lifetime invalidation is documented;
- errors are ordinary, domain-specific values;
- convenience functions may wrap mechanisms, but may not hide unbounded allocation or blocking;
- imports link only used code;
- target support is stated per module and unsupported operations fail during checking or linking;
- a module earns its place by hiding substantial policy or implementation behind a small interface.

## Package map

Top-level names answer "what am I doing?". Submodules answer "which format or protocol?". Avoid
category directories such as `base`, `data`, `conv`, and `util`: they make discovery depend on
knowing the library author's taxonomy.

```text
std/
  mem                 arenas, marks, scratch scopes, pools, free lists
  bytes               compare/search/split/replace, byte builder and cursor
  str                 UTF-8 string views, ASCII, parse, construction
  utf8                validation, decode, encode
  unicode             tables and Unicode properties/casing
  fmt                 formatting into caller storage
  math                scalar math
  rand                deterministic generators and distributions
  sort                in-place sorting/search
  hash                non-cryptographic hashes and checksums

  io                  Reader/Writer function seams, buffering, copy, limits, cursors
  os                  processes, environment, signals, mappings, clocks, platform facts
  fs                  files, directories, app dirs, atomic replacement, watches, temporary files
  path                lexical portable paths
  term                console streams, ANSI, terminal capabilities and input
  flag                command-line flags, arguments, subcommands, help
  log                 structured/procedural logging to an explicit writer
  progress            bounded nested progress reporting
  debug               panic, stack traces, crash diagnostics, hex dumps
  semver              semantic-version parse, order, format, ranges

  time                duration, instant, wall time, UTC date/time
  sync                threads, atomics, mutexes, condition variables, jobs
  net                 IP, DNS, TCP, UDP, Unix sockets, polling
  net/url             URL parse/escape/build
  net/http            HTTP messages, client, server, routing, cookies
  net/websocket       WebSocket handshake and codec
  net/tls             TLS interface plus supported implementation

  encoding/base64
  encoding/binary     endian scalars, varints, signed/unsigned LEB128
  encoding/csv
  encoding/hex
  encoding/ini
  encoding/json
  encoding/xml
  compress/deflate
  compress/gzip
  compress/zstd
  archive/tar
  archive/zip
  crypto/aes
  crypto/hmac
  crypto/random
  crypto/sha2

  regex               compiled byte/UTF-8 matching
  reflect             helpers over compiler metadata
  testing             assertions, fixtures, subprocesses, golden/property tests, benchmarks
  profile             bounded tracing and timing
  dynlib              dynamic-library loading
  c                   C ABI aliases and string adapters
```

Names intentionally changed from current sketch:

- `flags` -> `flag`, matching use-site action and Go convention;
- `data/json` -> `encoding/json`, because format modules encode/decode rather than own "data";
- `os/fs` -> `fs`; ordinary file work should not hide below operating-system mechanisms;
- `os/path` -> `path`, containing both lexical and host/target-native operations;
- `math/rand` -> `rand`; randomness is not primarily mathematics;
- URL and HTTP live below `net`, where users seek network protocols;
- `term/print` stays as `term`; printing is one operation, not package identity.

`core` and `base` should be implementation-only if needed. Applications should not need to know
bootstrap layering.

## Inclusion tiers

### Foundation

Always portable and dependency-free: `mem`, `bytes`, `str`, `utf8`, `fmt`, `math`, `sort`, `hash`,
`io`, `encoding/*`, `testing`. These modules must work over slices, arenas, and function pointers,
not libc.

### System

Adapters supplied for every supported target: `os`, `fs`, `path`, `term`, `time`, `sync`, `net`,
`dynlib`. Platform-only declarations belong in explicit submodules such as `os/linux`, never in a
supposedly portable interface.

### Application

Deep common policy: HTTP client/server, TLS, archives, compression, regex, CLI help, logging,
profiling. These make standard library feel complete. Each needs at least two repository applications,
malformed-input tests, fuzzing where parsers exist, and cost/ownership documentation.

`net/tls` and `compress/zstd` are included batteries even when backed by a provider. Their public
interfaces remain Dyn-shaped, provider ownership/linking stays explicit, and supported provider
versions form part of release testing.

Foreign product bindings such as SDL and SQLite belong in an SDK `vendor/` collection or separate
official packages. Shipping them is useful; calling them language standard creates versioning and
link-provider obligations unrelated to Dyn semantics.

## Vendor library

SDK ships a sibling `vendor/` tree for useful third-party integrations:

```text
sdk/
  std/
    ...
  vendor/
    sqlite
    sdl3
    vulkan
    openssl
    zstd
```

Imports make status obvious:

```dyn
use "std/net/tls"
use "vendor/sqlite"
use "vendor/sdl3"
```

`vendor` means maintained adapter, not bundled native binary and not stable language surface.
Each module documents supported upstream versions, required link inputs, ownership, thread rules,
target support, and whether dependency is system-provided, vendored source, or dynamically loaded.

Rules:

- `std` may use a private provider adapter, but its public interface never exposes provider types;
- applications may import `vendor` directly for provider-specific capability;
- vendor modules contain Dyn-shaped ownership wrappers, not only copied foreign declarations;
- generated raw bindings normally live in `raw_generated.dyn` inside the same module and remain
  non-`pub`; a `raw/` submodule would force declarations public across the module seam and is used
  only when direct low-level access is intentionally supported;
- modules require CI against supported upstream versions and one executable example;
- upstream breaking changes may break `vendor` during minor releases, with migration notes;
- no transitive auto-linking or hidden runtime installation;
- project-local vendored dependencies use a separate project dependency root, so SDK `vendor/`
  cannot shadow application code.

## Memory model

### Primary interface: arenas

Retaining operations should normally accept `*mem.Arena` directly. This communicates lifetime,
mark/rewind ability, zeroing, and bulk invalidation—facts erased by a generic allocator.

```dyn
result := json.parse(source, arena)
text := str.join(parts, separator, arena)
file := fs.read(path, arena)
```

Callers needing bounded behavior use fixed arenas. Callers needing growth use a chained arena.
Frame/request storage uses reset. Temporary work uses a scratch scope. Pools and free lists obtain
their backing region from an arena, then manage reuse inside that region.

Recommended hierarchy:

```text
OS pages / caller byte slice
          |
        Arena
       /  |  \
 scratch pool free-list
          |
   application structures
```

Scratch should be a scoped value, not only arena selection:

```dyn
temp := mem.scratch_begin(scratch_pool, conflicts)
defer mem.scratch_end(&temp)
work(temp.arena)
```

`Scratch` owns mark plus selected arena. This makes correct cleanup one operation and gives tests a
place to detect bad nesting. No global or implicit scratch context.

### Generic allocator: deferred

Odin currently represents an allocator as a procedure pointer plus `rawptr` data
([runtime definition](https://github.com/odin-lang/Odin/blob/master/base/runtime/core.odin#L2794-L2855)). Its procedure
supports multiple modes: allocation, free, free-all, resize, queries, and zeroed/non-zeroed forms.
Dyn should not add either contract yet. Arena plus caller-provided slices cover current standard
modules while preserving more lifetime information than a generic allocator.

If real workloads later require allocator substitution, smallest candidate remains:

```dyn
struct Allocator {
  data: rawptr,
  allocate: *fn(data: rawptr, size: usize, alignment: usize) mem.Allocation,
}
```

Possible future contract:

- `Allocation` reports success and returned byte region; exhaustion is ordinary;
- normal allocation is zeroed, matching `arena_try_push`;
- measured hot paths may call an explicitly named concrete operation such as
  `arena_try_push_uninit`; generic `Allocator.allocate` remains zeroed and zeroing behavior is never
  selected by a boolean argument;
- alignment must be nonzero power of two;
- zero-size allocation succeeds with empty storage and need not return unique address;
- returned memory remains valid until adapter owner's documented bulk invalidation point;
- interface provides no individual free or resize;
- caller cannot infer lifetime, thread safety, rewind, ownership, or release from `Allocator` alone.

Potential adapters: arena, chained arena, and failure-injection storage. Do not publish this seam
until at least two real callers require substitution. Do not mechanically change arena-taking
interfaces to allocator-taking interfaces.

Why alloc-only: it describes shared capability of arena, scratch, chained arena, and monotonic test
storage. Adding `free` implies semantics arenas cannot honor usefully. Adding a mode enum makes every
adapter understand unrelated requests and turns simple allocation into runtime dispatch plus a large
behavioral contract.

### Pools and free lists

A free list is arena-backed indirectly: initialize it from a byte slice carved once from an arena.
It then recycles fixed-size slots inside that region. Freeing a slot returns it to the list, not to
the arena. Arena reset/rewind/release invalidates the whole free list and every live slot.

```dyn
memory := mem.arena_push(arena, slot_count * slot_size, slot_alignment)
list := mem.free_list_init(memory[..slot_count * slot_size], slot_size, slot_alignment)
```

Provide an arena convenience constructor only if repeated setup proves noisy. Keep
`free_list_init([]u8, ...)` canonical because stack arrays and externally mapped regions are equally
valid backing storage.

Basic free lists remain fixed-capacity. A growing free list may retain `*Arena`, allocate another
chunk on exhaustion, and return slots individually to its own lists; chunks still die together with
the arena. Give growing behavior a distinct type because allocation failure, pointer lifetime, and
cost differ.

Modules requiring arbitrary independent reclamation need a different, richer type—provisionally
`Heap`—or own a pool/free-list explicitly. `Heap` should not enter std until real long-lived workloads
establish required allocate/free/resize semantics.

## I/O seams

`io.Reader` and `io.Writer` are justified function-pointer seams because files, sockets, TLS streams,
compression streams, memory cursors, and tests all vary there. Each is exactly two words: `rawptr`
state plus one function pointer. Each interface has exactly one operation:

```dyn
struct Reader {
  data: rawptr,
  read: *fn(data: rawptr, destination: []u8) io.Result,
}

struct Writer {
  data: rawptr,
  write: *fn(data: rawptr, source: []const u8) io.Result,
}
```

Buffering, exact reads, copy, limits, hashing, and encoding belong behind procedural helpers. Avoid a
wide hierarchy of seek/close/flush interfaces. Capabilities such as seeking and closing remain on
concrete modules unless multiple adapters prove a shared seam. Leaf operations keep concrete types:
`fs.read`, `net.receive`, `tls.read`, and `fmt.write` do not require wrappers. Adapt only where
composition pays: `io.copy`, streaming codecs, compression, HTTP bodies, logging sinks, and tests.

Formatted output is a procedural helper over that same seam:
`io.print(writer, "count: {}", count)`. A `Writer` is passed by value because it is only two words
and the helper does not mutate it. `terminal.stdout()` and `terminal.stderr()` construct writers;
Dyn has no methods, so a chained `io.stderr.print(...)` API would add a second object model for no
additional capability.

Do not store these adapters inside every resource. Construct cheap borrowed views at composition
sites, such as `fs.reader(&file)` or `tls.writer(&connection)`. Adapter does not own or close state.
This prevents interfaces spreading through ordinary code and keeps lifetime/resource operations on
concrete modules.

## Collections constraint

Dyn has no generics. A universal typed `List(T)` or `Map(K,V)` cannot be designed honestly today.
Do not compensate with reflection-heavy, `rawptr` public containers: that moves element size,
alignment, copying, hashing, and type safety into every caller.

Near-term batteries:

- excellent slices, byte/string builders, bit sets, rings, pools, and free lists;
- concrete maps needed by standard modules kept private;
- documented recipes for application-specific typed vectors/hash tables;
- optional generated collection source if tooling can preserve readable ordinary Dyn.

A public collection design waits for either deliberate language support or a proven code-generation
workflow. This is largest current gap between "any application" and Dyn's small-language constraint.

## Common interface rules

1. Borrowing transforms return views; retaining transforms take destination slice or arena.
2. Bounded form is canonical. Growing convenience form accepts arena explicitly.
3. Expected failure returns status/result. `must_` or infallible form panics only on invariant failure.
4. Names use module context: `json.parse`, not `json.parse_json`; `fs.open`, not `os.file_open`.
5. Blocking, allocation, copying, retained borrows, thread safety, and invalidation appear in docs.
6. Option structs appear only when optional policy would otherwise produce multiple booleans or many
   near-duplicate functions.
7. Provider adapters stay below stable Dyn-shaped interfaces.
8. Convenience belongs in std when it removes repeated error-prone policy, not when it only aliases a
   syscall or foreign function.

## Migration

1. Treat empty `std2/` tree as design inventory, not destination architecture.
2. Freeze current `compiler/std` behavior; record representative application workflows.
3. Establish `mem`, `io`, and result conventions first. Everything else depends on these seams.
4. Move one vertical workflow at a time: CLI file transform, HTTP client, HTTP server, archive reader,
   then threaded application.
5. For each moved module, migrate two real applications and delete old implementation. Avoid wrapper
   layers retaining both package maps.
6. Add a searchable generated package index with examples, ownership, errors, blocking, allocation,
   and target support. Discoverability matters as much as package count.
7. Rename freely while pre-1.0, then declare a small stable foundation before stabilizing application
   modules.

## Decisions still needed

- Is generated typed collection code acceptable, or must collections wait for language support?
- Must every supported target implement every System operation before release, or can modules publish
  smaller target-specific capability sets?

## Resolved design choices

- TLS and zstd ship in std with explicit provider details.
- One `path` module handles lexical and native path operations; no separate `filepath` package.
- Allocation is zeroed by default; explicitly named non-zeroed concrete allocation is permitted for
  measured hot paths. Generic `Allocator` remains zeroed and one-operation.
