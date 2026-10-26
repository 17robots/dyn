# Releasing

Pushing a `v*` tag publishes a release. Everything before the tag is ordinary
review; the tag is the only step that ships.

## Steps

1. Rename the changelog's `## Unreleased` section to the version, for example
   `## 0.1.0-preview.21`, and merge that change. Breaking releases also add a
   guide under `docs/migrations/` and link it from the changelog.
2. Tag the merged commit on `main` with `v<version>` and push the tag.
3. `.github/workflows/release.yml` runs and publishes only when every job passes:
   - `linux`: the C compiler suite, sanitizers and the relocated SDK
     (`c-compiler.yml`);
   - `native`: runtime and std tests on native Linux AArch64, macOS and Windows
     runners (`native-targets.yml`);
   - `compiler-hosts`: the compiler built and tested on macOS and Windows hosts
     (`compiler-hosts.yml`);
   - `vendors`: vendor bindings against native libraries (`vendor-native.yml`);
   - `bundle`: `tools/prepare-release.py` checks every job's evidence and
     checksums, assembles the archives and creates the GitHub release.
4. Point the README and `mise.example.toml` at the new version and its
   checksums, then update `dyn-editors` (`scripts/update-release.py <version>`)
   and downstream projects.

Running the workflow by hand (`workflow_dispatch`) validates a version without
publishing.

## Checking locally

| Command | Checks |
| --- | --- |
| `just test` | Smoke programs and the full regression suite (`tests/run.py`) |
| `just release-check` | The standalone release gate and a relocated SDK package |
| `just bench-scale` | Compile-speed floors and linear growth on generated programs |
| `just test-vendors` | Vendor ABI bindings and the Tree-sitter provider binding |
| `just artifact dyn-sanitize` | A compiler built with ASan and UBSan; run tests with `DYN=build/dyn-sanitize` |

Syntax changes land in the compiler's parser and in `tree-sitter-dyn` (editor
highlighting) together. `grammar.lock.json` pins only the grammar that
`just test-vendors` parses with to qualify the `vendor/tree_sitter` binding;
`tools/fetch-grammar.py` fetches it.

## Support scope

| Surface | Status |
| --- | --- |
| Compiler host | Linux x86-64; macOS and Windows hosts are built and tested in CI |
| Linux x86-64 output | Primary target |
| Linux AArch64, macOS AArch64, Windows x86-64 output | Tested on native runners every release |
| `riscv64-linux`, `x86_64-macos`, `aarch64-windows` output | Experimental; cross-compiled, not natively qualified |
| `wasm32-browser`, `wasm32-wasi` | Experimental |
| `riscv64-none` (bare metal, QEMU virt board) | Experimental; run under `qemu-system-riscv64` when installed. See [bare metal](../guide/bare-metal.md) |
| `riscv32-none` (bare metal, QEMU virt board, RV32GC) | Experimental; run under `qemu-system-riscv32` when installed. `tools/backend/bare-differential.py` compares the value corpus with x86-64 Linux |
| `thumbv7em-none` (bare metal, QEMU mps2-an500 board, Cortex-M7) | Experimental; run under `qemu-system-arm` when installed. `tools/backend/bare-differential.py --target thumbv7em-none` compares the value corpus with x86-64 Linux |
| Vendor packages | Optional; qualified on Linux x86-64 |
| Crypto and TLS | Known-answer and malformed-input tests; no independent audit |

Dyn is pre-1.0. See [stability](../guide/stability.md) for what may change
between releases.
