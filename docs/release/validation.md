# Preparing a Linux x86-64 preview

Freeze the candidate source, then run from the complete workspace:

```sh
just release-check
```

This runs compiler/LSP tests, C sanitizers and static analysis, SDK/provider
contracts, conformance/soak/reproducibility tests, real Neovim completion and
highlight edits, SDL lifecycle/audio checks, standalone component builds,
performance checks, and relocated SDK/source packages. It stops at the first
failure. A report is written even on failure; logs are in `build/release-check`.
Missing required dependencies fail preflight instead of turning into green skips.
No command publishes a release.

`RELEASE_FLAGS=--preflight just release-check` only inspects prerequisites.
`RELEASE_FLAGS=--list` prints stages. `--only STAGE` is for iterating on a failure;
it always produces a **partial** report and cannot qualify a release.

The suites currently share `build/` and fixture paths. Do not run other builds or
modify candidate sources during a release check. Custom `BUILD` directories are
not supported by this aggregate workspace gate. Component builds still support
their documented output overrides.

## Toolchain

[toolchain.json](toolchain.json) records the CI baseline and immutable revisions
for dependencies built from source. CI uses LLVM/Clang 19, Tree-sitter runtime and
generator 0.25.8, Zig 0.16.0, and Neovim 0.11.3. Use
`RELEASE_FLAGS=--baseline just release-check` to require the baseline. Local runs
record the actual versions; they must not be advertised as baseline qualification.

System packages remain distribution-managed, not byte-for-byte pinned. Their
versions and the SDK's linked dependencies are retained. Pinned source revisions
improve repeatability but do not make the entire OS/toolchain hermetic.

`python3 tools/setup-release-providers.py` builds SDL3, SDL3_image, SDL3_ttf,
Tree-sitter C, Vulkan headers, and the additional game/asset/audio providers into `build/vendor-deps/install`. It requires a
C/C++ toolchain, CMake, Git, FreeType/Harfbuzz and image development libraries;
the CI setup lists the distribution packages. Add `neovim` explicitly to build
the pinned editor. Nothing installs into `/usr`. The release command discovers
libraries in that prefix; add its `bin` directory to PATH for Neovim.

Vulkan headers use the existing host Vulkan loader. Their recorded version is
the header version, not a claim about the loader or driver. OpenGL smoke tests
use SDL's offscreen driver by default; `DYN_TEST_GL_DRIVER` selects another.

## Performance

The gate saves frontend check time, peak RSS, compiler allocation counts, and LSP
latency samples in `build/readiness/scaling.json`. Debug/release code-generation
phase times and RSS are recorded in `build/readiness/compiler-phases.json`; the
cache benchmark checks warm rebuild speed against clean builds. Existing scaling checks reject
superlinear work independently of absolute wall time. Large-function and member
work checks remain separate workloads.

For comparisons, collect repeated reports on an idle, fixed runner first. Copy an
accepted report outside the output directory, then pass
`--performance-baseline /path/to/accepted.json`. The benchmark rejects a different
machine identity. Its existing tolerances are 35% plus 2 ms for compile time,
25% plus 4 MiB for RSS, and 50% plus 2 ms for editor p95. Allocation counters also
have explicit tolerances. Do not compare these thresholds across shared CI hosts.
Baseline updates require an explanation and retained before/after reports;
never automatically replace a failing baseline with the current result.

## Native and hardware evidence

The existing CI workflow cross-builds target probes, then executes them on
Windows x86-64, macOS ARM64 and Linux ARM64 runners. Each runner now saves a JSON
report containing its real host, exit results and hashes of the executed files.
A cross-link report alone does not qualify a target. Compiler hosting remains
Linux x86-64; these jobs qualify generated programs, not a native Windows compiler.

`python3 tests/sdl3-applications.py` uses contract doubles for frame lifetime,
expose/resize redraw, close, minimization and audio failures/timeouts. It also
runs real SDL dummy audio in debug/release. Add `--gpu` on a graphics-capable
machine to require three GPU submissions in both modes. The manual hardware
workflow requires a self-hosted Linux x86-64 runner labelled `dyn-gpu` with the
same dependencies and a working graphical session. No hardware pass is inferred
from configuration or mocks. Audio drain does not prove audible output: listen
to the short tone on the release hardware and record device/driver and result.

## Editor distribution and publication

Neovim tests use the real editor, its LSP client and the current generated Dyn
parser. They check acceptance without an inserted slash, nested import
completion, const/import diagnostic recovery, semantic ranges and Tree-sitter
captures after edits and line insertion.

For Zed, publish the grammar repository first, update the extension pin and
provenance together, then run `just verify-published-grammar`. That read-only check
records `build/readiness/published-grammar.json`. The installed extension must
also be exercised in Zed. Publishing requires the chosen remote and revision;
a locally matching grammar is insufficient.

On success the release gate records source and archive hashes, generates release
notes, and prepares versioned copies in `build/release-check/artifacts`. Upload
those exact files with the report/checksums; do not rebuild after approval. The
CI workflow uploads evidence and candidate archives as workflow artifacts, and
can be started manually. It does not create public tags or releases. Before
publication, review [notes](notes-0.1.md), [compatibility](../stability.md), and the
explicit pending external evidence in the report.

Optional asset/UI providers are also built from their staged sources under
ASan/UBSan by `tests/vendor-sanitize.py`, required by the release check. Run
`just vendor-libs` first; missing staged sources fail this check.

Raw vendor binding gates regenerate every provider from the installed development
headers, validate C/Dyn layouts in debug and release, then import every package
and exercise native calls. See [raw vendor APIs](../vendor-raw-bindings.md) for
the full header/dependency set and preprocessor/feature limitations.

The vendor setup gate installs the SDK under a path containing spaces, generates
Lua bindings with the installed tools, checks quoted activation and preservation
of existing library paths, and executes the shipped arena/native-lifetime example.

The browser-Wasm gate requires Node and wasm-ld and executes the JavaScript module
interface in debug/release, including a Clang ABI oracle and buffer-backed arenas.
The installed SDK gate repeats it using the relocated compiler and runtime.
FFmpeg raw tests require all seven core development libraries; versions and the
selected header surface are recorded with the generated binding report.

Wasm arena-growth, WASI Preview 1 and browser FFmpeg engine gates are required.
The FFmpeg core is downloaded on first use with a fixed SHA-512 check and cached
under `build/browser-ffmpeg`. No runtime CDN is required by the browser example.
Actual browser UI qualification is a separate Playwright run; its report lives in
`build/wasm-next/browser-ui.json` when performed locally.
