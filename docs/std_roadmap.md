# Dyn Stdlib Roadmap (Zig + Odin Informed)

This roadmap maps Dyn stdlib growth against:

- Zig std docs entry: https://ziglang.org/documentation/master/std/
- Zig std source index (top-level): `ziglang/zig` `lib/std`
- Odin core modules: https://github.com/odin-lang/Odin/tree/master/core

## Current Dyn Std Surface

Current modules under `std/`:

- `bytes`, `collections`, `diag`, `env`, `fmt`, `fs`, `heap`, `io`, `math`, `mem`, `os`, `path`, `str`

## External Module Families Observed

Top-level Zig/Odin families repeatedly represented:

- alloc/mem/containers (`heap`, `mem`, `container`, `array_list`, `hash_map`, `sort`)
- io/fs/os/path/env/process/time
- strings/text/unicode/strconv/encoding
- net/http
- crypto/hash/random
- sync/thread/atomic
- debug/log/testing

## Proposed Dyn Priorities

## Phase 0 (foundation hardening)

- `std/alloc`: allocator traits/helpers, allocation statistics/debug hooks.
- `std/collections`: split monolith into `vec`, `deque`, `map`, `set`, `queue`, `stack` modules.
- `std/strconv`: stable parse/format for ints/floats/bools.
- `std/unicode`: utf-8 validation + scalar iteration utilities.
- `std/testing`: lightweight assertion/test helpers used by std and examples.

Implementation notes:

- Keep modules as thin wrappers over runtime/OS boundaries where needed.
- Reserve `$...` for language builtins; bind runtime symbols through explicit `extern` declarations in std modules.
- Prefer a layered approach (`std/os/*` raw syscall/runtime boundary -> pure Dyn wrappers -> higher-level `std/io`/`std/fs` APIs).
- Track runtime compatibility aliases as stable vs transitional and retire transitional entries when extern-based std coverage is in place.
- Prefer value-safe APIs (`?T`/`!Err`) over sentinel values.
- Add execution tests first for every new module primitive.

## Phase 1 (platform and text breadth)

- `std/process`: process args/env/cwd/exit/status/subprocess APIs.
- `std/time`: monotonic/realtime clocks, duration helpers.
- `std/log`: severity + sink-based logging.
- `std/encoding`: base64/hex/json helpers (incremental, composable APIs).

Implementation notes:

- Reuse `std/os/*` layering pattern (`os` facade + platform backend modules).
- Keep Linux first, but isolate platform branches early for portability.
- Keep syscall number tables per arch (for example `x86_64` vs `aarch64`) under platform-specific submodules.

## Phase 2 (networking and security)

- `std/net`: sockets, address parsing, basic TCP helpers.
- `std/http`: request/response framing and minimal client API.
- `std/hash` and `std/crypto`: checksums + secure hash primitives first.
- `std/rand`: deterministic PRNG + entropy-backed random API.

Implementation notes:

- Start with low-level primitives, then add convenience wrappers.
- Separate deterministic algorithms from OS entropy sources.

## Suggested Next Deliverables

- `std/collections/map` + `std/hash` (unblocks many higher-level modules).
- `std/strconv` + `std/unicode` (unblocks robust io/json/http text handling).
- `std/process` + `std/time` (unblocks tooling and diagnostics improvements).
