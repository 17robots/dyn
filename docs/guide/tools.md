# Tools

## The `dyn` command

| Command | Does |
| --- | --- |
| `dyn check DIR` | Parse and type-check a module; libraries need no `main` |
| `dyn vet DIR` | Check, then report suspicious but valid code; exits 1 on findings |
| `dyn build DIR` | Build an executable (`--debug` default, or `--release`) |
| `dyn run DIR` | Build and run |
| `dyn fmt DIR` | Format every file in the module: one statement per line, two-space indentation, a space after commas; `--check` only reports |
| `dyn docs DIR` | Print public declarations and their contracts; `--json` for tools |
| `dyn query DIR` | Export a semantic program index as JSON |
| `dyn lsp` | Run the language server on stdio |
| `dyn cache` | Inspect or clean the shared compilation cache |

`dyn help` lists every option. Useful ones: `--target` to cross-compile,
`--diagnostics json` for machine-readable errors, `--timings`, `--no-cache`
and `--link PATH` to add a native object or library.

The compiler generates machine code directly for every target, in debug and
release builds. There is no LLVM backend; `--backend llvm` reports an error.
See the [independent toolchain guide](independent-toolchain.md).

The compiler reports errors only. `dyn vet` runs extra checks on valid code: it
flags copying an arena (the copies would hand out overlapping memory) and
importing one module under two names. Language servers show the same findings
as warnings. Run `dyn vet` in CI next to `dyn fmt --check`.
Editor packages for VS Code, Zed, Neovim, Helix and Sublime live in the
`dyn-editors` repository and all use `dyn lsp`.

None of the tools below add ownership annotations, garbage collection or an
effect system.

## Compiler lifetime diagnostics

`dyn check` and `dyn build` reject some proven straight-line escapes through local
pointer/slice aliases and direct aggregate fields. They also diagnose reads/writes
through tracked arena allocations after `std/mem.arena_reset`.

This is deliberately incomplete. Control-flow joins, deferred cleanup, indirect
writes and unknown calls discard facts. Rewind offsets, failed release, foreign
code, concurrent access and arbitrary alias graphs are not proved safe. A successful
check is not a lifetime proof. Continue following the [memory rules](memory.md).

## Semantic program database

```sh
dyn query app --target x86_64-linux > build/program.json
dyn-query build app --output build/program.sqlite
dyn-query symbol build/program.sqlite save_name
dyn-query callers build/program.sqlite save_name
dyn-query sql build/program.sqlite 'select name,type,path,line from symbols where kind=?' function
```

The SDK installs `dyn-query`; in a source checkout run `python3 tools/dyn-query.py`. Extraction resolves imports and types and
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

`slot_map.resolve` returns the live slot or the caller's read-only stub, so a
stale handle reads as empty data instead of failing.

## Capabilities and execution isolation

`std/fs/capability` is Linux-only. `Directory` borrows a live directory descriptor;
its default descriptor is invalid. The owner closes it after consumers finish.
`read` permits one bounded read of a relative path beneath that directory, rejecting
absolute paths, parent escapes and symlinks with Linux `openat2`. Unsupported kernels
fail closed. It returns `Read(count)` or `Failed(errno)` and can record resource events.

This interface does not restrict arbitrary native code: raw syscalls remain possible.
For untrusted preview programs, use the separate runner:

```sh
dyn-sandbox app/main.dyn
# Explicitly expose an approved directory, read-only:
dyn-sandbox example.dyn --read ./fixtures
```

In a source checkout run `python3 tools/dyn-sandbox.py`. Linux, Bubblewrap, enabled user namespaces
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

## Benchmarks

`just bench-scale` measures cold `check`, debug and release builds on generated
programs and fails below the lines-per-second floors in
`tools/scale-benchmark.py`. `python3 tools/performance-suite.py` runs the wider
performance suite.

For a paired end-to-end comparison of a qualified compiler candidate with the
production artifact, build both first, then run on an idle machine:

```sh
python3 tools/compare-compilers.py --reference build/dyn-release \
  --candidate path/to/candidate/dyn --runs 5 \
  --output build/compiler-comparison
```

The output directory must be new. Both compilers receive the same generated
multi-module and flat sources, standard library, build flags, and job count.
Compiler order alternates; caches are disabled. The report retains each sample,
phase timings, binary/source/runtime hashes, build records, executable output
checks, artifact sizes, and peak RSS. RSS is a per-process maximum, not aggregate
simultaneous process-tree memory. No compiler default or performance threshold
changes. Override `--lines`, `--flat`, and `--jobs` to choose workload sizes and
parallelism. A short correctness smoke uses `--lines 1000 --flat 10 --runs 1`;
its timings are not evidence of a general speedup.

During the parser migration (preview 24) the handwritten parser made the
500k-line `check` about 1.9 times faster with about 40% less peak memory than the
Tree-sitter frontend, at eight jobs with matching outputs. Raw samples were local
build artifacts and are not retained.

Release-policy profiling uses an isolated standard-library workload and alternates
policy order. Run it separately from builds and other benchmarks:

```sh
python3 tools/performance-suite.py --samples 3 --profile-ir \
  --output build/release-profile
```

The report records cold-cache, warm-cache, novel-edit and executed-runtime samples,
artifact sizes, compiler/SDK hashes and command environments. Cold caches mean
empty compiler caches, not empty OS page caches. The optional IR profile emits a
separate monolithic optimized module; its size does not describe the modular
objects used in the timed builds. Per-module phase sums overlap under parallel
compilation and must not be treated as disjoint wall-clock costs.

A local three-sample run on 2026-10-13 produced these medians:

| Release policy | Cold build | Warm build | Edited build | Runtime | Executable bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| Portable default | 0.135 s | 0.019 s | 0.071 s | 0.165 s | 29,576 |
| Native CPU | 0.147 s | 0.020 s | 0.072 s | 0.165 s | 35,000 |
| Optimization level 3 | 0.144 s | 0.019 s | 0.070 s | 0.166 s | 29,768 |
| No LTO | 0.154 s | 0.019 s | 0.046 s | 0.161 s | 150,264 |

All variants produced matching runtime output. Disabling LTO improved this edited
build but increased executable size about 5.1 times and slowed the cold build.
This single workload does not justify changing defaults. The separate optimized
IR outputs were 330,644 bytes for portable, 389,612 for native and 351,041 for O3,
each with 11 function definitions. The no-LTO monolithic IR matched portable;
that does not establish equivalence of their modular build paths. Raw evidence
is in `build/release-profile-final/{results,summary,ir-profiles}.json`.
