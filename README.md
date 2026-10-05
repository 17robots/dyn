# Dyn compiler

Dyn is ready for public preview testing. Start with
[preview 16](https://github.com/17robots/dyn/releases/tag/v0.1.0-preview.16), then
[report bugs](https://github.com/17robots/dyn/issues). APIs may change between previews.
See the [changelog](CHANGELOG.md) for upgrade notes and code migrations.

This repository contains the C bootstrap compiler, target runtime, SDK (`std/`
and optional native bindings in `vendor/`), compiler tools and regression tests.
The grammar lives in [17robots/tree-sitter-dyn](https://github.com/17robots/tree-sitter-dyn).
Editor extensions and applications are separate projects.

Preview 7 fixes repeated compilation in `dyn run`, including invocation through
PATH, and avoids oversized LLVM values for large struct/array copies and literal
assignments. Unchanged modules reuse the cache; source edits still rebuild their
module. Use `--timings` to inspect compilation and `--no-cache` to force a rebuild.

On x86_64 Linux with LLD, release builds emit ThinLTO summaries and cache native
backend results under `DYN_CACHE_DIR` (or the normal Dyn cache). Relinking reuses
unchanged backend work; `--no-cache` bypasses this cache too. LLD periodically
prunes the backend cache to 10% of available disk space or 1 GiB, whichever is
smaller, and removes entries unused for seven days. `--jobs` also limits ThinLTO
backend workers. Cold release builds still perform LLVM optimization.

Use `dyn build --release --no-lto src` when cold-build latency matters more than
cross-module optimization. This keeps per-module O2 optimization and emits native
objects directly, avoiding link-time optimization. Executable performance and size
can differ; benchmark your workload before choosing this for distribution. The
cache distinguishes this mode from normal release builds.

## Install a preview

| System | Download from the release |
| --- | --- |
| Linux x64, glibc 2.39+ (Ubuntu 24.04 or current Arch) | `dyn-0.1.0-preview.16-linux-x86_64-glibc2.39.tar.gz` |
| Windows x64 (10/11 or Server 2022) | `dyn-0.1.0-preview.16-windows-x86_64.zip` |
| macOS 15+, Apple Silicon | `dyn-0.1.0-preview.16-macos-aarch64.tar.gz` |

The SDKs include the compiler, standard library, runtime, host linker and library
dependencies. LLVM, Tree-sitter, MSYS2 and Homebrew are not required to use the
prebuilt SDKs. Choose either mise or a manual download below.

### With mise

1. [Install mise](https://mise.jdx.dev/getting-started.html) (tested with 2026.9.9).
2. Create a directory for your program. Copy [mise.example.toml](mise.example.toml)
   into it as `mise.toml`, or copy the mise configuration from the release notes.
   Merge both Dyn tables if you already have a config; keep the platform checksums.
3. Run these commands in that directory (PowerShell, Bash or Zsh):

```sh
mise trust
mise install github:17robots/dyn
mise exec -- dyn version
```

Expected version: `dyn 0.1.0-preview.16`. No compiler checkout is needed.
`mise exec -- dyn ...` works without shell activation. To use plain `dyn`, follow
[mise's shell setup](https://mise.jdx.dev/getting-started.html).

For use across projects, merge the same two tables into your global mise config
(normally `~/.config/mise/config.toml`), then install as above.
[Configuration locations and overrides](https://mise.jdx.dev/configuration.html).

**Updating:** replace both Dyn tables with the next release's configuration and
run `mise install github:17robots/dyn` again. The current setup pins filenames and
checksums as well as the version; changing only the version or running
`mise upgrade --bump` is insufficient.

### Manual download

Download your SDK from the release table above and extract the whole archive.
Keep `bin`, `lib` and `share` together; copying only the executable is insufficient.
The release notes contain SHA-256 checksums. `runtime-sources` and GitHub's
"Source code" downloads are not needed to run Dyn.

On Linux/macOS, from the directory containing the downloaded archive:

```sh
# Linux; substitute the macos-aarch64 archive name on macOS.
tar -xzf dyn-0.1.0-preview.16-linux-x86_64-glibc2.39.tar.gz
./dyn-sdk/bin/dyn version
export PATH="$PWD/dyn-sdk/bin:$PATH"
```

On Windows, in PowerShell:

```powershell
Expand-Archive .\dyn-0.1.0-preview.16-windows-x86_64.zip -DestinationPath .\dyn-preview16
.\dyn-preview16\dyn-sdk\bin\dyn.exe version
$env:Path = "$PWD\dyn-preview16\dyn-sdk\bin;$env:Path"
```

These PATH changes last for the current shell. For future shells, add the SDK's
absolute `bin` path to your shell profile or Windows user Path setting.
macOS binaries are ad-hoc signed, not notarized; macOS may require you to approve
the downloaded application before running it.

## Run your first program

Create `hello/main.dyn` in your project directory:

```dyn
use "std/io"

fn main() {
  result := io.println(io.stdout(), "Hello, Dyn!")
  if result.status == io.Status.Error { #panic("could not write output") }
}
```

With mise:

```sh
mise exec -- dyn check hello
mise exec -- dyn run hello
```

With a manual installation on PATH, use `dyn check hello` and `dyn run hello`.
Expected output: `Hello, Dyn!`. No package manifest is needed for this example.
To build an executable, use `dyn build hello --release --output hello-app`
(`--output hello-app.exe` on Windows). Prefix with `mise exec --` when using mise.

Standard streams are `io.stdin()`, `io.stdout()` and `io.stderr()` on all three
native hosts and WASI. They borrow process handles and use caller-owned buffers.
Use `std/bufio` for line input. Streams preserve bytes: Windows console encoding
follows its code page. `bufio.read_line` strips LF or CRLF and preserves lone CR.
Preview 3 callers must rename `terminal.stdin/stdout/stderr` to their `io`
equivalents. `std/terminal` retains Linux terminal controls and key decoding.

## Standard library contracts

The executable [memory patterns](docs/memory-patterns.md) cover fixed budgets,
constant array sizes, explicit growth, scratch, retained output, and failure behavior.
For local compiler/grammar development in the combined workspace, set
`TS_DIR` to the sibling `tree-sitter-dyn` checkout containing the matching generated
parser. The workspace justfile does this automatically. The standalone grammar pin
must be advanced to the matching published grammar before releasing these syntax changes.

The current source tree provides these APIs and ownership contracts. Source changes
may be newer than the latest published preview.

| API | Contract |
| --- | --- |
| `std/fs` | Basic open/create/append/exclusive-create, read/write, seek/sync, close and stream adapters work on Linux, macOS and Windows. Directory traversal, metadata and atomic replacement remain Linux-specific; watching is available through the separate portable watch module. |
| `fs.File{}` | Unopened. Use `fs.take(&file)` to transfer ownership, `fs.borrow(&file)` for a view, and `adopt_handle`/`borrow_handle` for native handles. Closing a borrowed or already-closed file returns `InvalidState`. |
| `bufio.read_line` | Strips LF or CRLF, preserves lone CR. Returns `bufio.ReadStatus.More` when the destination fills: process those bytes and continue the same line. `Complete` ends a line; `End` may include a final fragment; `Error` reports failure. |
| `process.arguments(&arena)` | Includes argv[0]; descriptors and bytes belong to the arena. Unix preserves native bytes; Windows converts UTF-16 to UTF-8. Linux reads `/proc/self/cmdline`; macOS and Windows use native process data. |
| `time.try_monotonic_now()` / `try_realtime_now()` | Fallible native clocks; monotonic measures durations, realtime uses Unix epoch. `sleep_result` reports failure. Date and duration helpers are portable; WASI supports clocks but not sleep. |
| `std/errors` | Portable `kind` accompanies the original native `error` code. Check `ok` or `status` first: library failures may have code zero. |
| `std/sync` | Atomics, mutexes, conditions, semaphores and once initialization work on Linux x64/ARM64, macOS ARM64 and Windows x64. Darwin mutexes use ownership-aware unfair locks; other waiters use native address waits. |
| `std/thread` / `std/net` | Thread lifecycle and TCP/UDP, IPv4/IPv6, DNS, socket options and poll work on all four native targets. Epoll remains Linux-only. Winsock initializes once per process. Darwin binaries require macOS 15 or newer. DNS uses native cryptographic entropy and portable UDP truncation detection for TCP fallback. |
| `net.Connection{}` / `net.Listener{}` | Inactive, including results from failed constructors. Successful values own their descriptors; do not copy owners. Stream adapters borrow the connection's address. Close each successful owner; writes to disconnected sockets return errors without SIGPIPE. |
| `std/fs/watch` | Non-recursive watches use Linux inotify, Windows asynchronous directory changes or macOS FSEvents. Inactive/failed opens are safe to close. Overflow requires rebuilding and reconciling the directory snapshot; consult the platform capabilities below. |
| `std/encoding/json` | Parsing and both string-writing APIs reject invalid UTF-8. Arena parse failures rewind allocations. Streaming writer errors can leave earlier output written; check status and transferred bytes. |

File owners must not be copied; this remains a programmer obligation. A borrowed
file must not outlive its owner, and stream adapters borrow the File's address.
Use `defer` to close owners. Caller buffers back reads, buffered I/O and environment
values. `fs.read_all` and `process.arguments` allocate in your arena, rewind on
failure, and return memory valid until that arena is reset, rewound or destroyed.
No hidden heap ownership is transferred to the caller.

Migration: replace raw `File{ descriptor: ... }` construction with an explicit
adopt or borrow operation. Line results now use `bufio.ReadStatus`, and a full
buffer is `More`, not an I/O error. Use `read_until` for byte-exact delimiters.

## Library qualification

`just test` includes fragmented CSV/XML inputs, malformed JSON and allocation
limits, socket/watch cleanup, generated binding ABI checks, and a small expression
compiler written in Dyn. The expression compiler tests scanning, precedence,
symbol lookup, bounded output and diagnostics; it is not a self-hosted Dyn compiler
or a bootstrap-equivalence test.

Native host CI executes stdlib contracts and the Tree-sitter provider lifecycle
against each host's installed library. Linux also qualifies the selected providers
in `just test-vendors-native`. These gates qualify their named providers and host
versions, not every optional provider or every ABI/version combination.

`thread.spawn_with_size(&thread, bytes, entry, context)` owns the native stack
until successful join. Linux maps and releases it explicitly; Windows/macOS use
OS-managed stacks. The existing `spawn` borrows a caller stack on Linux and uses
its length as an OS stack-size request on Windows/macOS. The thread and context
must remain valid and unmoved until join; live owners must not be copied.

Watcher owners and their caller output buffers must remain alive until successful
close. Windows/macOS allocate one bounded native state block and support 16
watches per owner. Windows waits for cancelled I/O completion before releasing
that block; macOS stops delivery and drains callbacks before release. Native
allocation/handle failures remain errors rather than successful silent skips.
Names are borrowed: copy them before the next `next()` call for portable code.

`HasCloseWrite`, `HasMoveCookies`, `HasDirectoryFlag`, `SupportedEvents` and
`FixedWatchCapacity` expose watcher capabilities. Linux provides close-write and
paired rename cookies. Windows provides rename actions without cookies or
close-write/directory flags. macOS events may coalesce; rename reports both move
bits and requests a rescan. Unsupported-only masks fail. Default `Changes` works
on every native platform; it does not promise unsupported details. Zero fixed
capacity on Linux means there is no userspace slot bound, while kernel quotas
still apply.

`tools/setup-vendor-tests.py` builds pinned optional test dependencies into the
build directory. `just test-vendors-all` requires all 23 raw-binding manifest
providers, native media/adapter workflows, and asset/UI sanitizer checks. Missing
providers fail the gate. The Linux gate also runs before release publication.
Reports record generated ABI fingerprints, provider metadata and source pins;
this is representative native qualification, not proof of every provider API or
Windows/macOS vendor support. Native host CI executes thread, synchronization,
network and watcher contracts on Windows/macOS; cross-linking is a separate check.

## Build from source

Install Git and clone the public compiler repository, then choose your host below:

```sh
git clone https://github.com/17robots/dyn.git
cd dyn
```

These commands build current `main`. To build the published preview instead,
run `git checkout v0.1.0-preview.16` before continuing. Source builds normally report
`0.1.0-dev`; set `DYN_VERSION=0.1.0-preview.16` if you need that embedded version.
Source builds require their build-time libraries and linker to remain installed.

### Linux x64 (Ubuntu 24.04)

Run in Bash. Building requires a C++ compiler and LLVM development headers for
the ThinLTO writer, plus the C compiler. Install LLVM/Clang/LLD 19 and the pinned
Tree-sitter runtime:

```sh
sudo apt-get update
sudo apt-get install -y build-essential python3 clang-19 llvm-19-dev lld-19
mkdir -p build/deps
git clone --depth 1 --branch v0.25.8 https://github.com/tree-sitter/tree-sitter build/deps/tree-sitter-runtime
sudo make -C build/deps/tree-sitter-runtime install PREFIX=/usr/local
sudo ldconfig
export LLVM_CONFIG=llvm-config-19
export CLANG=clang-19
export PATH=/usr/lib/llvm-19/bin:$PATH
python3 tools/fetch-grammar.py
python3 tools/build.py host
python3 tests/compiler-host.py
./build/dyn-release version
```

### macOS Apple Silicon

Install Xcode Command Line Tools (`xcode-select --install`) and
[Homebrew](https://brew.sh/), then run in Bash or Zsh:

```sh
brew install llvm@19 lld@19 tree-sitter python
export PATH="$(brew --prefix llvm@19)/bin:$(brew --prefix lld@19)/bin:$PATH"
export CPPFLAGS="-I$(brew --prefix tree-sitter)/include -L$(brew --prefix tree-sitter)/lib"
export CC=clang CLANG=clang LLVM_CONFIG=llvm-config
python3 tools/fetch-grammar.py
python3 tools/build.py host
python3 tests/compiler-host.py
./build/dyn-release version
```

### Windows x64

Install [MSYS2](https://www.msys2.org/) and open its **CLANG64** shell. Run
`pacman -Syu` first, reopening the shell and repeating if MSYS2 requests it.
Clone the repository above if you have not already, then run from its directory:

```sh
pacman -S --needed git mingw-w64-clang-x86_64-clang mingw-w64-clang-x86_64-llvm mingw-w64-clang-x86_64-lld mingw-w64-clang-x86_64-python mingw-w64-clang-x86_64-libtree-sitter
export CC=clang CLANG=clang LLVM_CONFIG=llvm-config
python tools/fetch-grammar.py
python tools/build.py host
python tests/compiler-host.py
./build/dyn-release.exe version
```

Use `./build/dyn-release run path/to/project` (`.exe` on Windows) to try your
source build. Keep the compiler in its build directory so it can locate the SDK.
The grammar fetch uses `grammar.lock.json`; generated sources stay under ignored
`build/deps/tree-sitter-dyn`. Set `TS_DIR` for a separate generated grammar checkout.

## Development and preview limits

The Linux full suite additionally needs `just`, Zig 0.16.0 and Python 3.12+;
[the CI setup](.github/actions/setup-compiler/action.yml) records the dependencies.
`just test` covers compiler, LSP, lifetime, semantic and ABI regressions.
[Native host CI](.github/workflows/compiler-hosts.yml) tests Windows/macOS compiler
and standard streams; native output jobs execute 14 Windows, 14 macOS and 12 ARM
Linux probes. `python3 tests/standard-streams.py --host-only` tests host streams.
`python3 tests/stdlib-host.py` exercises portable files, ownership, arguments,
clocks and line boundaries in debug and release builds, also against installed SDKs.

For a local source installation on Linux/macOS:

```sh
PREFIX="$HOME/.local/opt/dyn" python3 tools/install.py --host
export PATH="$HOME/.local/opt/dyn/bin:$PATH"
dyn version
```

In CLANG64, use `python tools/install.py --host` with `PREFIX` set to your chosen
installation directory. This copies the SDK but does not bundle third-party host libraries. The release packaging jobs do.
`just package` creates the relocatable Linux SDK using the release build environment.

This is a preview, not a stable language/API promise. Intel Mac downloads,
Windows ARM downloads, Alpine/musl and older glibc are not supported by these SDKs.
Optional native providers and cross-target toolchains have additional requirements.
Native terminal controls remain Linux-only. Arenas and borrowed values require
explicit lifetime care; lifetime diagnostics are not general memory safety.
Use `dyn help`, `dyn docs MODULE --json` and `dyn query PROJECT --json` to explore.

## Report a bug

[Open an issue](https://github.com/17robots/dyn/issues/new) with your `dyn version`,
OS/architecture, installation method, exact command, full error and a small Dyn
program that reproduces it. For a crash or wrong output, include expected versus
actual behavior. Try debug and `--release` builds when the difference matters.

Releases are gated on compiler, native output, SDK and mise checks. Published tags
and assets are not replaced. Licenses stay in the archives; checksums and mise
configuration are in release notes; validation reports stay in Actions. The extra
Linux runtime-source archive supplies corresponding sources for bundled GNU libraries.

## License

Copyright (c) 2026 Matthew Dray <mdray@duck.com>. See [LICENSE](LICENSE) and
[third-party notices](THIRD_PARTY_NOTICES.md). Commercial application development
is allowed. Dyn modifications and independent distributions are restricted by the
license. This is source-available software, not open source.

### Performance controls and measurement

The default release policy remains portable O2. Optional controls:

- `--cpu native` targets this host's CPU/features. Do not distribute that binary
  to machines lacking those features. Cross-target use is rejected; cache keys
  include the resolved CPU and features.
- `--release --opt-level 3` requests LLVM O3, including the ThinLTO backend.
  Measure runtime, size and build time; O3 is not universally faster.
- `--release --debug-info` retains optimization, including inlining. Debug info
  no longer implicitly adds `noinline` to every function.
- `--opt-remarks` reports inlining, vectorization, unrolling and sample-profile
  decisions (compiler stderr and linker stdout; capture both). It disables caches
  and uses one worker for readable
  output; do not use this diagnostic mode for build-time comparisons.
- `--release --sample-profile profile.prof` consumes an LLVM sample profile on
  x86_64 Linux with ThinLTO/LLD. It emits the source information needed by the
  profile loader. Missing/invalid profiles fail the build; profile content is
  part of the cache identity. It cannot combine with `--no-lto`, `--no-link`,
  shared builds or standalone IR/object/assembly output.

For sample PGO, build with `--release --debug-info`, record a representative
workload with an external sampling profiler, convert it to LLVM's sample format,
then rebuild with `--sample-profile`. Keep source paths and source revision stable:
module symbols currently include a path-derived identity. Dyn does not bundle a
profiler or automatically train profiles. Verify applied samples with
`--opt-remarks`; synthetic test profiles prove plumbing, not performance gains.
See [LLVM's sampling workflow](https://clang.llvm.org/docs/UsersManual.html#using-sampling-profilers).

Run the isolated cold/warm/edited/runtime matrix with:

```sh
python3 tools/performance-suite.py --dyn build/dyn-release --samples 7
python3 tools/benchmark.py --samples 7 --require-stable-output \
  --artifact build/program --output build/runtime.json -- build/program
```

The matrix writes raw JSON samples, executable sizes, stdout/checksums, compiler
version, timing and per-child resource usage into a new build directory. It edits
only its own fixture copy. Cold means an empty compiler cache with OS page caches
retained; edited samples use novel executed code, not alternating cached versions.
`max_rss_bytes` is the OS child maximum, **not** aggregate concurrent process-tree
memory. Compare on the same machine and LLVM/toolchain, without competing builds.
The general benchmark runner also supports `--reset-dir` for cold builds; both
compiler cache and output artifact must be inside that dedicated directory.
See [performance qualification](PERFORMANCE.md) for measured results and limits.

### Allocation and copying contracts

Dyn arrays and structs have value semantics; slices borrow their backing storage.
Copying a slice or an arena/container handle does not clone its backing allocation.
Use pointers for intentional mutation; do not copy a live owning arena and release
both copies. Arena rewind/reset invalidates affected views. The compiler already
uses bounded memory copies for large values; pointer arguments are not assumed
non-aliasing merely because they are `const`.

- `std/bytes/search`: reusable KMP pattern with caller-owned prefix storage.
  Preparation is O(needle length), each search is O(text length), with no hidden
  allocation. Both needle and table must remain alive and unchanged. Prefer it
  for repeated searches or adversarial repeated-prefix input; simple one-off
  searches remain available in `std/bytes`.
- `std/container/string_map.reserve`: reserve capacity before bulk insertion to
  avoid intermediate arena tables. Keys are copied; growth preserves key bytes.
  `clear` reuses the table but retains key allocations. Deletion does not reclaim
  arena memory. Never rewind storage belonging to a live map.
- `std/bytes/builder.reserve`: extends the last arena allocation in place when
  possible; otherwise copies live bytes to new storage. Interleaved allocations
  can therefore increase retained storage. Reacquire views after mutation.
- `std/bufio`: large writes bypass staging copies while retaining a buffered tail.
  Short writes, ordering, partial errors and sticky errors retain their contracts.
- `std/testing.summarize`: caller-owned sample statistics without allocation;
  sorts samples in place. `std/mem.arena_snapshot` supplies used/peak/failure
  counters, and `std/observe` supplies optional allocation event records.

Performance changes must preserve empty inputs, overlap rules, arithmetic bounds,
allocation-failure behavior and ABI contracts. `tests/performance-contracts.py`
checks these alongside independent search oracles and compiler option/cache tests.

The source checkout includes experimental [primitive allocators and typed
allocation builtins](docs/allocator-design.md). These require the matching local
grammar checkout until its dependency revision is published and pinned.
