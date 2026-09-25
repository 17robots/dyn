# Dyn compiler

This repository contains the C bootstrap compiler, target runtime, shipped SDK
(`std/` and optional native bindings in `vendor/`), compiler tools and regression
tests. The grammar lives in [17robots/tree-sitter-dyn](https://github.com/17robots/tree-sitter-dyn).
Editor extensions, applications, benchmarks and the development workspace are
separate projects and are not included here.

## Build

Linux source builds use Ubuntu 24.04 with LLVM/Clang/LLD 19 and the
Tree-sitter 0.25.8 runtime is the CI baseline. You also need a C11 compiler,
Python 3.12+, Bash, Git and `just`. Zig 0.16.0 is needed for cross-target tests.

```sh
export LLVM_CONFIG=llvm-config-19
export CLANG=clang-19
export PATH=/usr/lib/llvm-19/bin:$PATH
just release
./build/dyn version
just test
```

`just release` fetches the exact grammar revision in `grammar.lock.json` into
ignored `build/deps/tree-sitter-dyn`. Generated parser sources stay in that
external checkout. Dyn does not regenerate or vendor them. For grammar development,
set `TS_DIR=/absolute/path/to/tree-sitter-dyn` to use your own generated checkout.
The Tree-sitter runtime library is a separate build dependency, not that grammar.
`.github/actions/setup-compiler/action.yml` records the pinned CI dependency setup.

Override `BUILD`, `CC`, `CLANG`, `CFLAGS`, `CPPFLAGS` and `LLVM_CONFIG` as needed.
A custom compiler output path may require `DYN_SDK` pointing to this repository;
installed SDKs locate their own runtime and standard library.

Native compiler host CI also builds and runs Dyn on macOS Apple Silicon and
Windows x64, packages their dependencies, and tests installation through mise
with build-tool paths removed. The default output target matches the host.

For a host-only source build, install LLVM, Clang and the Tree-sitter C runtime,
then run `python3 tools/fetch-grammar.py`, `python3 tools/build.py host`, and
`python3 tests/compiler-host.py`. The compiler is `build/dyn-release` (Windows:
`build/dyn-release.exe`). macOS uses Homebrew LLVM 19 and LLD 19 for linking;
Windows uses MSYS2 CLANG64's native Clang/LLVM, LLD, Python and **libtree-sitter**
packages. Use the environment setup in `.github/workflows/compiler-hosts.yml`.
Windows module compilation currently runs serially; POSIX hosts retain isolated
parallel workers. The host tests cover build/run, cached output replacement,
source changes, paths with spaces, diagnostics and LSP pipes. They gate releases
alongside the existing cross-target executable tests.

## Test and install

```sh
just smoke          # debug/release compiler and SDK smoke test
just test           # compiler, LSP, lifetime, semantic, ABI and C failure regressions
just native-probes  # cross-build; native execution requires matching CI hosts
PREFIX=/usr/local DESTDIR=/path/to/staging just install
just package        # archive, manifest, checksum and relocated debug/release smoke
```

Native CI executes 14 Windows x64, 14 macOS Apple Silicon and 12 Linux ARM probes.
These qualify generated programs in addition to native compiler host tests.
`just test` covers this standalone compiler. It does not run the former workspace's
application, editor-extension, graphics/audio or optional-provider qualification.
The SDK has additional platform/provider requirements beyond these core tests.

The standalone regression suite is in `tests/`. `src/` is the compiler implementation;
`runtime/` contains target support. SDK modules retain their source-level API and
ownership comments. Use `dyn docs MODULE --json` for declarations and
`dyn query PROJECT --json` for semantic project inspection. Run `dyn help` for
current commands. Arenas and borrowed values still require explicit lifetime care;
limited lifetime diagnostics are not general memory safety.

## Releases and mise

Pushing an unused `vVERSION` tag runs compiler/package validation and native target
tests, verifies mise installations, then publishes Linux x86-64, Windows x64 and
macOS Apple Silicon SDKs. Licenses stay inside archives; checksums and pinned mise
configuration appear in release notes. Test reports stay in Actions artifacts.
One additional Linux runtime-source archive accompanies the three SDK downloads. Suffix versions such as
`v0.1.0-preview.2` publish as prereleases. Manual release runs do not publish.
`DYN_VERSION` embeds the release version; normal builds default to `0.1.0-dev`.
Do not move published tags or replace released assets.

Copy `mise.example.toml` into your project's `mise.toml` (or merge its tool entry
into an existing config), then run:

```sh
mise trust
mise install
mise exec -- dyn version
```

The example pins `0.1.0-preview.2` with its archive checksum. For installation
across projects, add the same tool entry to `~/.config/mise/config.toml` and run
`mise install github:17robots/dyn`. Each new release includes its pinned
mise configuration in the release description. This uses mise's GitHub backend, not a custom plugin.
Starting with preview 2, Linux x86-64 SDKs bundle LLVM 19, Tree-sitter 0.25.8,
LLD and their non-glibc dependencies. They require glibc 2.39 or newer (Ubuntu
24.04 and current Arch Linux); Alpine/musl and older glibc are not supported.
No system LLVM or Tree-sitter installation is needed. Use the release's
mise configuration for its exact version and platform checksums. Linux/Wasm linking uses
bundled LLD; other cross-target tools and optional native providers remain external.
The release gate tests the archive in clean Ubuntu and Arch containers and through
mise before publication. Preview 1 still needs its original system dependencies.

Starting with preview 3, Windows x64 and macOS 15+ Apple Silicon archives bundle
their host libraries and LLD linker. No MSYS2 or Homebrew installation is needed
to run those SDKs. macOS binaries are ad-hoc signed, not notarized; Intel Macs are
not included. Optional providers and cross-target toolchains remain external.

The earlier combined-workspace preview remains in Git history and its original
release assets. New archives contain only this compiler and its runtime/SDK.

## License

Copyright (c) 2026 Matthew Dray <mdray@duck.com>. See [LICENSE](LICENSE) and
[third-party notices](THIRD_PARTY_NOTICES.md). Commercial application development is
allowed. Dyn modifications and independent distributions are restricted by the
license. This is source-available software, not open source.
