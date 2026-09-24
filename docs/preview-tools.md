# Preview tools and guarantees

These additions use existing Dyn syntax. They do not introduce ownership annotations,
implicit garbage collection, or a new effect system.

## Compiler lifetime diagnostics

`dyn check` and `dyn build` reject some proven straight-line escapes through local
pointer/slice aliases and direct aggregate fields. They also diagnose reads/writes
through tracked arena allocations after `std/mem.arena_reset`.

This is deliberately incomplete. Control-flow joins, deferred cleanup, indirect
writes and unknown calls discard facts. Rewind offsets, failed release, foreign
code, concurrent access and arbitrary alias graphs are not proved safe. A successful
check is not a lifetime proof. Continue using the [memory contracts](memory.md).

## Semantic program database

Run from the workspace root:

```sh
./build/dyn query projects/memory-tour --target x86_64-linux > build/program.json
python3 compiler/tools/dyn-query.py --dyn ./build/dyn build projects/memory-tour --output build/program.sqlite
python3 compiler/tools/dyn-query.py symbol build/program.sqlite save_name
python3 compiler/tools/dyn-query.py callers build/program.sqlite save_name
python3 compiler/tools/dyn-query.py sql build/program.sqlite 'select name,type,path,line from symbols where kind=?' function
```

The installed SDK provides `dyn-query`. Extraction resolves imports and types and
checks all loaded function bodies for the selected target. SQLite tables contain
symbols, parameters, fields, expression references, calls, types and source
dependencies. Function symbol types are return types; parameters are separate.
The database records compiler/source hashes and rejects queries after source,
module membership or compiler changes. Build with a quiescent workspace. It is a
local snapshot, not a transactional filesystem or a durable symbol-ID service.

Scope: expression references only; type-use syntax is not indexed. Dependencies
include transitive source dependencies. Foreign/indirect call effects remain
unknown. Source comments remain author contracts, not inferred ownership/effect
proofs. IDs are snapshot-local. Invalid programs produce no semantic index.
`dyn docs` remains useful for cheap syntax-only SDK declaration lookup.

## Bounded runtime observation

`std/observe` stores events in caller-owned memory. A `Log` contains an event slice,
count and saturating dropped count. `record`, `recorded` and `clear` allocate nothing.
Events carry kind, numeric resource/value and optional borrowed source/line labels.

`mem.Arena` exposes peak usage and allocation-failure counts in `arena_snapshot`.
Attach `arena.events` and set `arena.event_resource` to record allocation, failure,
reclamation and release events. The log and labels must outlive recording and reside
outside memory reclaimed by that arena. There is no implicit synchronization or
whole-program tracing. Use one log per worker or synchronize externally.

`slot_map.lookup` returns `Missing` or `Present(bytes)` so the result itself expresses
whether a view exists. Present bytes remain borrowed. `copy_into` remains the way to
retain data in disjoint caller storage. Exhaustive `case` handling makes failure
states visible without making them exceptional.

## Capabilities and execution isolation

`std/fs/capability` is Linux-only. `Directory` borrows a live directory descriptor;
its default descriptor is invalid. The owner closes it after consumers finish.
`read` permits one bounded read of a relative path beneath that directory, rejecting
absolute paths, parent escapes and symlinks with Linux `openat2`. Unsupported kernels
fail closed. It returns `Read(count)` or `Failed(errno)` and can record resource events.

This interface does not restrict arbitrary native code: raw syscalls remain possible.
For untrusted preview programs, use the separate runner:

```sh
python3 compiler/tools/dyn-sandbox.py projects/hello/main.dyn
# Explicitly expose an approved directory, read-only:
python3 compiler/tools/dyn-sandbox.py example.dyn --read ./fixtures
```

The installed command is `dyn-sandbox`. Linux, Bubblewrap, enabled user namespaces
and libseccomp are required. Missing isolation never falls back to native execution.
Compilation and execution use separate namespaces; networking and process creation
in user programs are denied. No home directory is mounted. Approved read/write paths
appear at `/cap/read/N` and `/cap/write/N`. Mount only data intended for the program.
The trusted `/usr` toolchain is visible read-only; do not place secrets there.

Default limits: 20-second compile, 3-second execution, 64-KiB captured output,
32-MiB individual files, 2-GiB compiler/256-MiB program address space per process.
Compiler process counts have bounded headroom relative to the host UID, not a cgroup
budget. These controls reduce exposure; kernel vulnerabilities and aggregate hostile
traffic remain outside this implementation's guarantee.

## Browser workspace and playground

Open the repository in its devcontainer. Setup builds Dyn and runs the memory tour.
No host LLVM installation is needed. The Ubuntu 24.04 image uses LLVM 19 and pinned
Tree-sitter source. Image distribution packages are not bit-for-bit locked.

On a Linux host supporting the isolation requirements:

```sh
python3 playground/server.py
```

Open the printed token-bearing URL. The server binds loopback, limits concurrent
runs to two, checks host/origin/token, and never logs submitted source. For an
authenticated HTTPS port-forwarding service, supply `--origin https://EXACT_HOST`,
then open that origin with the printed `#token=...` fragment. Keep the forwarded
port private. Nested sandboxing may be unavailable in a hosted container; then
execution fails closed. A public anonymous service needs a dedicated deployment,
aggregate resource quotas and independent security review. This is a local preview,
not an already-published internet service.

## Validation and migration

```sh
just test-agent-readiness
just test-preview
```

`test-preview` exercises semantic lookup/freshness, memory events, capability escape
rejection and sandbox denial/limits. Its sandbox tests require Linux isolation.

Arena layout has changed: rebuild all Dyn modules and any FFI layout mirrors together.
Frontend cache epoch is 7. No syntax changes are required. See the
[AI trial](../benchmarks/ai/README.md) for measured task results and limits.
