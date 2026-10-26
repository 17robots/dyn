# Std standardization

Status: agreed 2026-10-22 and 2026-10-23; audited implementation closure
recorded 2026-10-24. The concrete violations identified by the std audits are
fixed and independently reviewed. The registered suite passes 183/183 gates
across combined original and resumed runs, with no reported prerequisite skips.
The final rerun from std lint onward passes 140/140 gates. This is not one
uninterrupted final-state run or a proof of every native-platform path. See the
[qualification record](qualification-20261024.md). Compatibility is not yet
frozen; these intentional API breaks precede the required two-preview window.

Math now includes scalar integer/float helpers, concrete vectors, matrices,
quaternions and ranges. Independent reviews found and resolved range midpoint
and operand-validation bugs and strengthened float/quaternion test coverage.
Target-gated native math lowering now has focused SSA/tree, hardware-emulator
and Wasm execution checks; unsupported operations retain portable calls. Floating-point sampling is
not a global accuracy proof. See the qualification record below and the
[std guide](../guide/std.md#math-conventions) for current conventions.

The model is Ryan Fleury's: storage belongs to the caller, misses are not
errors, arenas cannot fail, and real errors exist only where the program meets
the outside world.

## Current correction pass

The 2026-10-24 pass fixes sticky buffered I/O, INI and WebSocket errors; lazy zero-state SHA-256 initialization; sort miss positions; and Metadesk failure rollback/stubs. Flags and regex now take arenas, with explicit payload ownership and portable result metadata. URL, semver, JSON, Metadesk, PNG/QOI, INI, DER/PEM/certificate, ZIP/zstd, Unicode and byte-codec results now carry portable diagnostics. Thread creation returns stable arena-backed pointers, and XML has an iterative document tree. The structural IR dump is implemented and its focused regression passes.

Provider-backed crypto wrappers now use portable results and arena-backed AEAD
outputs. The structural IR dump and target-gated native math lowering are
implemented, reviewed and included in qualification. Physical board execution
and the two-preview stability period remain separate milestones.

The closure audits' concrete findings are resolved:

- Zero PRNG and HTTP workers are safe; worker startup uses stable arena-backed thread nodes.
- HTTP, buffered I/O, WebSocket and scanner/writer states preserve their first failures, including native error zero.
- Complete HTTP, DNS and process-capture outputs belong to caller arenas; capture limits are explicit policy.
- HTTP/WebSocket, TLS, terminal, capability, archive and codec results preserve portable and native diagnostics separately.
- Certificate subjects use complete provider formatting rather than a fixed 1024-byte output ceiling.
- Watchers preserve terminal failures on all three platform implementations; platform fault injection supplements cross-link checks.
- Text/HTML template exhaustion follows the arena panic contract.
- Clock reads and dependent waits, capture, profiling and benchmark operations return structured failures instead of panicking on OS errors.

Fixed-size key and hash outputs, binary/UTF primitives, individual socket
addresses, raw OS/C bindings and documented streaming buffers remain the narrow
exceptions. They do not exempt ordinary complete producers or stream error
diagnostics. Semantic regression tests and reviews establish this closure;
syntactic std lint alone does not.

## Rules

### 1. Storage is yours

Std does not own element types. The caller's struct carries its link fields
(`next`, `prev`, `hash_next`, `generation`) and std supplies `$T` functions
that walk them. There are no generic types; see
[the generics design](generics-design.md#decided-no-generic-types).

```dyn
struct Symbol { name: []const u8, hash: u64, hash_next: *Symbol, kind: SymKind }
nil_symbol: Symbol

sym := hash.find(table, h, "main", &nil_symbol)
```

### 2. Lookups never fail

A lookup that returns a pointer returns a stub on a miss: a zeroed module-level
value whose links point back at itself or at nil. A lookup that returns a
position returns the length on a miss, so the result is always a safe slice
bound. Compare with the stub or the length only when the miss matters.

```dyn
v := json.object_get(root, "name") // &json.nil_value on a miss
i := strings.find(text, ":")       // #len(text) on a miss
```

### 3. Results are returned, not written through out parameters

A result that may be absent is `{value, ok}`, or a plain value whose zero
means "absent" when rule 2 applies.

```dyn
file := fs.read_file(&arena, path)
if file.ok {
  use(file.value)
}
```

### 4. One way to produce data: into an arena

Functions that build data take `arena: *mem.Arena` first. There are no
`_into`, `_size` or `_count` variants; for a fixed buffer, wrap it with
`mem.arena_from_buffer`.

### 5. Real errors only at edges, in one shape

Edges are the OS, files, the network and parsing external input. Results there
use the field names `{value, ok, kind, error}`: `kind` is a portable
`errors.Kind` and `error` the native code. Parsers add `offset`. A parser
always returns a usable `root`, the stub when parsing failed, so navigation
works before `ok` is checked.

### 6. Stateful values keep their first error

Scanners, readers, writers and builders record the first error in their state.
Later calls do nothing. The caller checks `.error` once at the end.

### 7. Zero is initialization

Every public struct is valid when zeroed. `init` and `make` functions are
shortcuts only. `process.Options` changes so that zero descriptors mean
"inherit".

### 8. Panics are for bugs

Bounds, double frees and broken invariants panic. `try_` exists only where
running out is expected: fixed-buffer arenas (`mem.try_push*`) and
`sync.try_lock`/`semaphore_try_wait`.

### Stubs are read-only

A stub is a constant, so it lives in read-only memory:

```dyn
const nil_entity: Entity = {}
```

Reading through a stub is always fine. Writing through one is a bug and faults
on targets with memory protection; on bare metal without an MMU the write
lands silently. Std helpers take the stub as `*const T` and return `*T`; that
is the only place const is cast away.

Language change: `&` on a constant is allowed and gives `*const T`. The
constant is emitted once, in read-only data.

### Link field names

Intrusive helpers find fields by name, so the names are part of the API:

| Field | Type | Used by |
| --- | --- | --- |
| `next`, `prev` | `*T` | `list` (singly and doubly linked) |
| `first`, `last` | `*T` | `list` and `chunk`, on the parent or owner |
| `parent` | `*T` | tree helpers in `list` |
| `free_next` | `*T` | free-list reuse (`list.free_*`) |
| `key` | `[]const u8` | `hash` |
| `hash` | `u64` | `hash` |
| `hash_next` | `*T` | `hash` |
| `generation` | `u32` | `slot_map` |
| `count`, `items` | `usize`, `[N]T` | `chunk`, on each chunk |
| `total` | `usize` | `chunk`, on the list |

A struct in two lists of the same kind needs a second set of link fields and,
for now, a hand-written loop for the second list. Offset-taking forms
(`dll_push_back_at`) wait for a real case.

Free lists use `free_next`, not `next`, so freeing a node that is still linked
elsewhere cannot corrupt that other list. Generic code cannot test for a field
that may be absent, so `free_push` does not check that the node was unlinked
first; that is the caller's job.

### Helper additions

- `slot_map.reset(node)`: zeroes the node except `generation`. Used when a
  freed slot is reused.
- `slot_map.retire(node)`: increments `generation`, so outstanding handles
  resolve to the stub.

### Typed reads: `get` and `parse`

One generic function per format replaces per-type getters and parsers:

```dyn
x := json.get(f32, item, "x")
name := json.get([]const u8, item, "name")
tags := json.get(*json.Value, item, "tags")
port := strings.parse(u16, text)
```

A miss, a type mismatch or bad text gives zero (`""`, the stub). Callers that
must reject bad human input check first:

```dyn
if !strings.valid(u16, text) {
  report("bad port: {}", text)
}
```

Supported types are integers of every width, `f32`, `f64`, `bool`,
`[]const u8` and, for documents, `*Value`. Another type panics on first use.
Inside std the body dispatches with a type `case` on `any`; no language
feature is added. `strings.parse_base(u64, text, 16)` covers other bases.
`xml` and `mdesk` get the same `get` where they have typed values. This
replaces `json.as_*` in the public API and `strings.parse_u64`, `parse_i64`,
`parse_f64` and `parse_u64_base`.

### Naming and comments

Functions are `verb_noun` and do not repeat the module name. Every public
function's comment uses the tags `mem` already uses where they apply:
Ownership, Invalidation, Allocation, Panics, Thread safety.

## Collections

There are no container types. Each job has one shape, built from slices,
plain structs and `$T` functions:

| Job | Shape |
| --- | --- |
| Fixed list | a slice: `mem.push_array(T, &arena, n)` |
| Growing list, own arena | a slice grown by `mem.append(&arena, &items, value)` |
| Growing list, shared arena | a chunk list |
| Structure: trees, free lists, membership in several lists | intrusive links (`list`) |
| Lookup by key | hash slots, `[]*T`, chained through `hash_next` (`hash`) |
| Stable references | `generation` handles (`slot_map`) |

A growing slice owns its arena. Its items are always the last thing on that
arena, so `append` pushes one element and lengthens the slice: nothing is
copied and item addresses never change. `append` panics when the slice no
longer ends at the arena top, which means something else pushed onto that
arena. A zero `Arena{}` reserves address space lazily, so one arena per list
is cheap on 64-bit targets; on targets without virtual memory, give it a
fixed buffer.

```dyn
struct Level { enemy_arena: mem.Arena, enemies: []Enemy }
mem.append(&level.enemy_arena, &level.enemies, Enemy{ hp: 10 })
```

A chunk list grows on any arena. The caller writes two small structs per
element type; `std/container/chunk` works through their field names:

```dyn
struct EnemyChunk { next: *EnemyChunk, count: usize, items: [64]Enemy }
struct EnemyList { first: *EnemyChunk, last: *EnemyChunk, total: usize }

e := chunk.push(&level.arena, &level.enemies, Enemy{hp: 10}) // *Enemy, stable
flat := chunk.to_slice(&scratch, &level.enemies)
```

Field names are listed under [link field names](#link-field-names).

## Language changes

Both land before the freeze:

- `&` on a constant gives `*const T`, emitted once in read-only data. Needed
  for read-only stubs.
- Function types drop the `*`: `fn(*Entity, i32) bool`. Parameter names are
  optional and documentary: `fn(target: *Entity, damage: i32) bool`. The
  existing `*fn(...)` sites are rewritten by script.

## Work by module

| Rule | Modules | Size |
| --- | --- | --- |
| 1 | new `container/list` (including `free_*`) and `container/hash`; read-only stubs (language change: `&` on constants); `slot_map` becomes intrusive; `string_map`, `mem.Pool` and `pool_*`/`acquire`/`release` are removed; `FreeList` stays only if a non-intrusive user remains | large |
| 2, stubs | `json` (plus `get`), `xml`, `zip/index`, `tar`, `flags`, `path` | medium |
| 2, length on miss | `strings`, `bytes`, `bytes/search` | small, many call sites |
| 3 | `strings.parse`/`valid`, `math`, `sort.search`, `utf8`, `utf16` | small |
| 4 | `strings`, `bytes`, `encoding/*`, `fmt` | medium |
| 5 | `fs`, `net`, `process`, `os/*`, `time`, and parsers: `json`, `xml`, `csv`, `ini`, `mdesk`, `png`, `qoi`, `semver`, `url`, `der`, `pem` | medium, mostly field renames |
| 6 | `bufio`, `io`, `bytes/builder`, `csv`, `websocket` | small |
| 7 | `process.Options`; check every public struct | small |
| Comments | all | mechanical |

Call sites in `tests/`, `projects/`, `vendor/` helpers and DNA move with each
change. One migration note in `docs/migrations/` covers the whole pass, and
`CHANGELOG.md` lists it under breaking changes.

The checker `tools/std-lint.py` flags selected out-parameter names, `_into`
forms, caller-storage size/count companions and isize-returning find functions.
It is a syntactic guard, not proof of every semantic rule or comment contract.

## Math

`std/math` now provides the portable API below. Sampled numerical regression
tests meet the accuracy target on the tested inputs; no global bound is
established. Fleury's code leans on concrete vector and range types, so std gets them
as ordinary structs (no generic types):

- Scalars, f32 and f64: `sqrt`, `floor`, `ceil`, `trunc`, `round`, `fma`,
  `copysign`, `sin`, `cos`, `tan`, `asin`, `acos`, `atan`, `atan2`, `exp`,
  `exp2`, `log`, `log2`, `log10`, `pow`, `hypot`, `is_nan`, `is_inf`,
  `lerp`, `unlerp`, `smoothstep`, `wrap`, constants (`pi`, `tau`, `e`,
  `inf`, `nan`, epsilons).
- Integers: `align_up`, `align_down`, `is_pow2`, `next_pow2`, `div_ceil`,
  `count_ones`, `leading_zeros`, `trailing_zeros`, `rotate_left/right`,
  checked and saturating add, sub and mul for every width, `sign`.
- Vectors: `Vec2`, `Vec3`, `Vec4` (f32), `Vec2i` (i32), with add, sub, mul,
  scale, dot, cross, length, normalize, lerp, min, max.
- Matrices and rotation: `Mat3`, `Mat4` (column-major, f32), `Quat`; multiply,
  transpose, inverse, translate, scale, rotate, look-at, perspective and
  orthographic projection.
- Ranges: `Rng1u64`, `Rng1i64`, `Rng1f32`, `Rng2f32` (rectangles), `Rng2i32`;
  contains, overlaps, intersect, union, pad, center, dimension, clamp.

Decided: `sqrt`, `floor`, `ceil`, `trunc`, `round`, `fma` and `copysign`
become compiler intrinsics, reachable only through `std/math`, that lower to one instruction where the
target has it and to a runtime helper elsewhere (soft-float targets). The rest
is plain Dyn, so results match on every target, including bare metal. Accuracy
target: within 1 ulp of a correctly rounded result for f64, checked against
the host libm in tests.

## Gaps after the freeze

These add API and break nothing. The user chose on 2026-10-26 to land them
before the freeze; see [std expansion](std-expansion.md).

1. Image encoders for `png` and `qoi` (done: both exist).
2. Text layout and font rasterization.
3. Graphics, GUI and audio: windowing, GPU and audio output stay in
   `vendor/` (SDL3, OpenGL, Vulkan, miniaudio). Std gains only portable,
   platform-free pieces written in Dyn: image encoders, font rasterization and an
   immediate-mode UI core that produces draw commands.
4. Native crypto to replace the OpenSSL-backed `aes`, `aead`, `signature`,
   `exchange` and `certificate`, and an audit of all of `crypto`.
5. `terminal` and `dynlib` beyond Linux (done 2026-10-26).
6. Embedded helpers beyond `mmio`: timers, interrupts and UART, now only in
   board test files.

## Order

1. This document, and the generics and self-hosting docs updated to match.
2. Rule 1: containers.
3. Rules 2 and 3.
4. Rule 4.
5. Rule 5.
6. Rules 6 and 7, comments, the checker.
7. Math.
8. Then the self-hosting order: IR dump, freeze, stage 0.

## Math qualification (2026-10-23)

All 145 registered gates pass across the initial, focused and resumed runs.
No internal skips were reported. Two harness fixes were needed: Python
3.11-compatible hash fixture escaping, and an explicit source SDK for
native-cache's private compiler copy. The latter still uses adjacent private
runtime objects for invalidation checks. Formatting changes were verified to
change whitespace only.

Per debug/release mode:

- Integers: 545,576 bigint pair cases, including exhaustive signed/unsigned
  8-bit pairs; 4,732 successful narrowing conversions and 1,116 panic cases.
- Float: corrected default regression has 1,153,931 comparisons. The alternate
  seed sweep has 11,793,931 comparisons. Exact primitives match bits; sampled
  transcendentals remain within 1 ulp of extended host libm. Width-specific
  f32 neighbors are checked for distinct bits and boundary bracketing.
- Vectors: 5,449 reference checks, 203 unit-length checks, ten overflow panics.
- Matrices/quaternions: 8,552 checks across 297 cases; twelve negative-control
  runs reject broken small-angle and shortest-angle conversions.
- Ranges: 2,160 interval checks, rectangle/clamp/boundary cases and nine
  rejections, including invalid second operands after an empty rectangle.

Eight additional RV32/Thumb hard/soft debug/release guests each pass 145
bounded checks. Soft images pass no-FP audits and disabled-FPU execution;
release wrappers select SSA. These samples extend backend coverage without
establishing universal bit agreement or a global transcendental error bound.
Matrix inversion remains sensitive to conditioning. Host-width usize/isize
integer tests do not independently exhaust ILP32 width behavior.

Logs and source hashes are retained under build/std-math-qualification,
including resume2-20261023-181309/report.txt and results.json. No commit was
made for this math layer in this continuation.

Math was committed as 08e91f5f890b on 2026-10-24. The standalone SDK packaging
and relocation gate passes for build/dist/dyn-0.1.0-dev-linux-x86_64.tar.gz.
This is a local development package, not a published preview release.

## Semantic compliance audit (2026-10-24)

The audit finds that intrusive containers, read-only stubs, unsigned search
positions, principal arena producers and active resource wrappers are migrated.
The initial findings now have focused regression coverage:

- `std-sticky.py` and `websocket-sticky.py`: first-error replay without later I/O, including empty buffered calls and zero native codes.
- `sha256-zero.py`: lazy initialization, explicit reset and sticky oversized-input failure against hashlib at block boundaries.
- `flags-arena.py` and `regex-arena.py`: ownership, rollback, borrowing, reusable workspace and exhaustion panics.
- Parser/codec result suites: portable categories, native zero, offsets and empty failure payloads for the migrated modules. QOI marker/run validation and semver offending-byte diagnostics have negative regressions.
- `std-miss-contracts.py` and `xml-tree.py`: sort length-on-miss, failure stubs, rollback, navigation and iterative deep XML trees.
- `thread-results.py`: stable arena-backed descriptors, lifecycle, zero joins, validation rollback and exhaustion.
- `producer-overlap.py`: ZIP and Unicode preflight preserve aliased input bytes. Official Unicode 17 conformance passes 403,031 vectors in each mode after arena migration.
- `math-lowering.py`: generic/native x86 feature gates, SSA/tree numerical oracles, argument order, spills, AArch64/RV64 execution and Wasm behavior. RV32/Thumb hard/soft samples retain no-FP audits.
- `std-lint.py`: multiline declaration recognition has independent scanner tests. It checks narrow syntactic heuristics, not ownership semantics or universal compliance.

A fresh closure audit and complete registered qualification are still required. Provider-backed crypto migrations and ownership/cost comments remain under review. This record does not turn earlier math-only qualification into qualification of the current working tree.

Fixed-size hash/key buffers, binary stores, encoding primitives, streaming and
raw OS/C bindings retain their documented exceptions. These are not blanket
exceptions for variable-size producers or stateful I/O after failure.
