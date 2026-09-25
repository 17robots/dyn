# Dyn compiler

Dyn is ready for public preview testing. Start with
[preview 5](https://github.com/17robots/dyn/releases/tag/v0.1.0-preview.5), then
[report bugs](https://github.com/17robots/dyn/issues). APIs may change between previews.

This repository contains the C bootstrap compiler, target runtime, SDK (`std/`
and optional native bindings in `vendor/`), compiler tools and regression tests.
The grammar lives in [17robots/tree-sitter-dyn](https://github.com/17robots/tree-sitter-dyn).
Editor extensions and applications are separate projects.

## Install a preview

| System | Download from the release |
| --- | --- |
| Linux x64, glibc 2.39+ (Ubuntu 24.04 or current Arch) | `dyn-0.1.0-preview.5-linux-x86_64-glibc2.39.tar.gz` |
| Windows x64 (10/11 or Server 2022) | `dyn-0.1.0-preview.5-windows-x86_64.zip` |
| macOS 15+, Apple Silicon | `dyn-0.1.0-preview.5-macos-aarch64.tar.gz` |

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

Expected version: `dyn 0.1.0-preview.5`. No compiler checkout is needed.
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
tar -xzf dyn-0.1.0-preview.5-linux-x86_64-glibc2.39.tar.gz
./dyn-sdk/bin/dyn version
export PATH="$PWD/dyn-sdk/bin:$PATH"
```

On Windows, in PowerShell:

```powershell
Expand-Archive .\dyn-0.1.0-preview.5-windows-x86_64.zip -DestinationPath .\dyn-preview5
.\dyn-preview5\dyn-sdk\bin\dyn.exe version
$env:Path = "$PWD\dyn-preview5\dyn-sdk\bin;$env:Path"
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

## Standard library in preview 5

Preview 5 includes the following APIs and ownership contracts.

| API | Contract |
| --- | --- |
| `std/fs` | Basic open/create/append/exclusive-create, read/write, seek/sync, close and stream adapters work on Linux, macOS and Windows. Directory traversal, metadata, watching and atomic replacement remain Linux-specific. |
| `fs.File{}` | Unopened. Use `fs.take(&file)` to transfer ownership, `fs.borrow(&file)` for a view, and `adopt_handle`/`borrow_handle` for native handles. Closing a borrowed or already-closed file returns `InvalidState`. |
| `bufio.read_line` | Strips LF or CRLF, preserves lone CR. Returns `bufio.ReadStatus.More` when the destination fills: process those bytes and continue the same line. `Complete` ends a line; `End` may include a final fragment; `Error` reports failure. |
| `process.arguments(&arena)` | Includes argv[0]; descriptors and bytes belong to the arena. Unix preserves native bytes; Windows converts UTF-16 to UTF-8. Linux reads `/proc/self/cmdline`; macOS and Windows use native process data. |
| `time.try_monotonic_now()` / `try_realtime_now()` | Fallible native clocks; monotonic measures durations, realtime uses Unix epoch. `sleep_result` reports failure. Date and duration helpers are portable; WASI supports clocks but not sleep. |
| `std/errors` | Portable `kind` accompanies the original native `error` code. Check `ok` or `status` first: library failures may have code zero. |

File owners must not be copied; this remains a programmer obligation. A borrowed
file must not outlive its owner, and stream adapters borrow the File's address.
Use `defer` to close owners. Caller buffers back reads, buffered I/O and environment
values. `fs.read_all` and `process.arguments` allocate in your arena, rewind on
failure, and return memory valid until that arena is reset, rewound or destroyed.
No hidden heap ownership is transferred to the caller.

Migration: replace raw `File{ descriptor: ... }` construction with an explicit
adopt or borrow operation. Line results now use `bufio.ReadStatus`, and a full
buffer is `More`, not an I/O error. Use `read_until` for byte-exact delimiters.

## Build from source

Install Git and clone the public compiler repository, then choose your host below:

```sh
git clone https://github.com/17robots/dyn.git
cd dyn
```

These commands build current `main`. To build the published preview instead,
run `git checkout v0.1.0-preview.5` before continuing. Source builds normally report
`0.1.0-dev`; set `DYN_VERSION=0.1.0-preview.5` if you need that embedded version.
Source builds require their build-time libraries and linker to remain installed.

### Linux x64 (Ubuntu 24.04)

Run in Bash. Install LLVM/Clang/LLD 19 and the pinned Tree-sitter runtime:

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
