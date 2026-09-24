# Compatibility and support policy

Dyn is pre-1.0. Source and standard-library compatibility may change, but changes must be recorded
in release notes and accompanied by migrations for shipped examples and tests. Core syntax should
be frozen during a release cycle; experimental APIs must not be presented as stable.

Implemented executable targets are Linux x86-64/AArch64, Windows x86-64, and macOS AArch64.
Linux x86-64 is the primary candidate target. Other targets remain experimental until
their native release gates have recorded passing results; configured CI jobs alone are not evidence.
macOS threads are intentionally unsupported until the freestanding/libSystem policy is chosen.
Unsupported names and incomplete executable links are rejected rather than
silently producing partial programs. Stable C interoperation means the documented ABI
for that target, not a cross-platform ABI promise.

Within one release line:

- patch releases fix defects without intentional source breakage;
- minor releases may add APIs and may make announced pre-1.0 corrections;
- removed APIs receive a release-note entry and repository-wide migration;
- debug diagnostics may improve, while release correctness semantics remain unchanged.

Releases should pass the C-compiler test/sanitizer matrix, deterministic clean rebuild checks,
integration projects, and the performance suite. A benchmark regression is evidence to investigate,
not by itself a correctness failure; accepted changes document their cause.
# Validation status

CI gates C bootstrap compiler with ordinary and sanitizer tests, relocated SDK
installation, deterministic release checks, malformed-input smoke tests, application
integration, and informational matched-Clang benchmarks. Benchmark numbers are not
portable pass/fail thresholds across shared CI hardware.

Long-duration production evidence remains maturity work; local validation does not establish it.

The authoritative current scope is [release readiness](release/readiness.md).

## Compatibility boundaries

| Surface | Policy before 1.0 | Required change evidence |
| --- | --- | --- |
| Syntax and semantics | Freeze within a release cycle; reject unsupported syntax consistently in compiler, grammar and editor. | Positive/negative fixtures, debug/release agreement, release note and migrated examples. |
| Public std/vendor APIs | Source compatibility within patch releases; announced pre-1.0 corrections may occur in a minor release. | Updated source contracts, reference generation, migrated repository clients and behavioral regression. |
| `.dynmi` interfaces and caches | Private, disposable implementation artifacts, not distribution formats. | Schema/version validation, epoch bump for semantic incompatibility, stale-cache rejection/rebuild. |
| Dyn objects/shared libraries | Compiler-version and target specific; no development binary ABI promise. | Rebuild every linked Dyn consumer/provider together; ABI probes for lowering changes. |
| C ABI | Selected target ABI for the documented C-compatible subset. | C header layout checks and bidirectional call probes on each target; provider version recorded. |
| LSP/diagnostics | JSON-RPC IDs and protocol shapes preserved; wording may improve. | Cancellation, edit recovery, diagnostic range and completion regressions. |

Serialized interface format has its own version; the frontend/cache epoch is
centralized as `DYN_FRONTEND_VERSION` in `compiler/src/dyn.h`. Epoch 6 adds target-sized Wasm layouts; rebuild compiler caches. Epoch 5 introduced
shared C-compatible struct lowering and revised semantic checks. A compiler
upgrade invalidates compiler-keyed object caches too. Never ship `.dynmi` or
cached objects as a stable SDK interchange format.

Every intentional break records old/new usage, affected versions, storage/lifetime
changes and migration tests in release notes. Experimental target support does
not become stable merely because a cross-linked artifact exists.

## Current development migrations

**Aggregate calls:** rebuild all objects, shared libraries and callback consumers
with the same compiler. C-compatible `struct Pair { x: i32, y: i32 }` can now cross
a C boundary by value; a `struct Text { bytes: []u8 }` still needs a pointer/length
adapter. Do not reuse an older Dyn callback pointer in a newly compiled provider.

**JSON membership:** previously `json.add(array, node)` twice could create a
cycle. Check the boolean return and create a separate node for a second parent:

```dyn
first := json.make_null(arena)
second := json.make_null(arena)
if first == nil || second == nil { return false }
if !json.add(left, first) || !json.add(right, second) { return false }
```

Keep arena storage and borrowed string/key bytes alive. Do not write `parent`,
`next`, `first`, or `last` manually. Allocate node storage using `#sizeof(json.Value)`
and `#alignof(json.Value)` if bypassing constructors; its size has changed.
`tests/sdk-api-contracts` checks membership rejection and retained text views.

**Analysis limits:** `dyn check --max-work N` opts CLI analysis into a work budget.
LSP defaults are 100,000,000 work units and 2,000 ms process CPU per dispatch;
`DYN_LSP_MAX_WORK` and `DYN_LSP_CPU_MS` override them (CPU maximum 60,000 ms).
A unit is an input byte or traversal checkpoint, not a stable complexity measure.
Cancellation returns JSON-RPC error -32800; exhausted request budget returns
-32803. Exhausted diagnostics publish an incomplete-analysis warning. Limits
are cooperative: blocking filesystem/provider calls are not preempted. Syntax
nesting remains capped at 1024 tree levels, module dependencies at 256 active
modules, and initializer graph traversal at 512 expression/block frames.

### SDL companion package paths

SDL_image and SDL_ttf now live under the SDL3 vendor family. Change
`use "vendor/sdl3_image" image` to `use "vendor/sdl3/image" image`, and
`use "vendor/sdl3_ttf" ttf` to `use "vendor/sdl3/ttf" ttf`. Function names,
surface/font ownership and native link names are unchanged. The old package
paths are removed; there are no duplicate forwarding packages. Importing only
`vendor/sdl3` still links only SDL3, without image or font dependencies.

`wasm32-browser` and `wasm32-wasi` are experimental module/command targets with
explicit trap and host-import contracts. See [WebAssembly](webassembly.md); native SDK portability
is not implied.


### Slot-map handle identity

`std/container/slot_map.Handle` now includes the generation-backing identity.
Rebuild all consumers; do not manufacture handles from an index/generation pair.
Obtain handles from `insert`, retain generation backing without clearing it, and
use `get` or `copy_into` before consuming a record. Handles from another backing
are rejected even when index and generation match. Serialized handles were never
supported. Raw views still expire at removal/reinitialization.
