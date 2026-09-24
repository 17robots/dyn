# Releases and mise

Dyn currently distributes an Ubuntu 24.04 Linux x86-64 compiler/SDK. Windows and
macOS CI execute generated programs; they do not produce native compiler downloads.
Windows users can use Ubuntu 24.04 under WSL2. macOS compiler hosting is not yet supported.

## Install the published preview

Install [mise](https://mise.jdx.dev/installing-mise.html). On Ubuntu 24.04 x86-64,
install the SDK's external dependencies:

```sh
sudo apt-get update
sudo apt-get install -y libllvm19 clang-19 lld-19 build-essential git python3
source_dir=$(mktemp -d)
git clone --depth 1 --branch v0.25.8 https://github.com/tree-sitter/tree-sitter "$source_dir/tree-sitter"
test "$(git -C "$source_dir/tree-sitter" rev-parse HEAD)" = f2f197b6b27ce75c280c20f131d4f71e906b86f7
sudo make -C "$source_dir/tree-sitter" install PREFIX=/usr/local
sudo ldconfig
export PATH="/usr/lib/llvm-19/bin:$PATH"
```

Copy [the example mise.toml](../../examples/mise/mise.toml) into your project, then:

```sh
mise trust
mise install
mise exec -- dyn version
```

The config pins the preview version, SDK asset, SHA-256, archive root stripping,
and `bin` directory. It uses mise's built-in
[GitHub backend](https://mise.jdx.dev/dev-tools/backends/github.html); no custom
plugin or registry entry is required. Keep `share/dyn` and the runtime objects
with `bin/dyn`; installing only the executable is insufficient.

The original `0.1.0-preview.1` download reports `dyn 0.1.0-dev` internally. Future
tagged builds embed their release version. Existing release assets remain unchanged.
Mise manages Dyn versions; it does not install these system shared libraries.
Cross-linking and optional SDK integrations need their own dependencies.

## Generate a release

`.github/workflows/release.yml` runs when a `v*` tag is pushed. It:

1. Validates the version and embeds it using `DYN_VERSION`.
2. Runs the full Linux release gate and both LLVM provider baselines.
3. Runs Windows x64, macOS Apple Silicon, and Linux ARM probes in debug/release.
4. Checks artifact hashes and successful evidence, then creates SDK, grammar,
   and example archives, license/notices, JSON results, checksums and `mise.toml`.
5. Installs the SDK through mise in an isolated directory, then compiles and runs
   a smoke program before publishing.
6. Creates the GitHub release only when all required jobs succeed. Versions with
   a suffix (for example `-preview.2`) are prereleases; plain versions are stable.

From the publishing checkout, choose the next unused version and push its tag:

```sh
git tag -a v0.1.0-preview.2 -m 'Dyn 0.1.0-preview.2'
git push origin v0.1.0-preview.2
```

Pushing the tag publishes automatically after validation. Do not move published
tags or overwrite assets. A rerun refuses to overwrite an existing release.
Manual workflow runs accept a version and generate CI artifacts without publishing.
The workflows must be present on the repository's default branch for GitHub's
manual-dispatch UI to expose them.

Each future release attaches a ready-to-copy `mise.toml` with its SDK checksum.
The repository example stays pinned to a known published preview until deliberately
updated. Release automation uses the tested Linux archive; it does not imply
Windows/macOS compiler distribution or a standalone, dependency-free SDK.

## Verification

- `python3 tests/release-bundle.py`: rejects incomplete or altered release inputs.
- `python3 tests/mise-package.py ARCHIVE --version VERSION`: tests an unpublished
  archive through mise's HTTP backend and runs a compiled program.
- `.github/workflows/mise.yml`: installs the actual public preview using the checked-in
  config, then compiles/runs on Ubuntu 24.04.
- Workflow definitions are checked locally with `actionlint`.
