# Linux developer-preview assessment — 2026-09-23

This pass addresses concrete SDK/binding defects before assessing a scoped Linux
x86-64 developer preview. Version stays `0.1.0-dev`. This is not a stable,
all-platform release signoff. Nothing has been published.

## Reproduced defects and fixes

- **Pool/free-list alignment:** requesting three 9-byte slots with alignment 1
  after a one-byte arena allocation panicked on a misaligned internal pointer.
  Effective alignment now includes the internal link alignment; both arena
  backing and slot stride use it. Caller-backed free lists validate their backing
  before linking nodes. Regression covers requested alignments 1–32, odd-sized
  slots, non-overlap, exhaustion, reuse, counts and direct caller storage.
- **C literal corruption:** `"/*keep*/"` became `""`; a URL containing `//` was
  truncated. Literal-aware comment handling preserves bytes and handles C line
  splicing before comments. C octal, hexadecimal and simple escapes translate to
  Dyn byte escapes; unsupported escapes are reported. Generated literal bytes
  are compared against an independently compiled C oracle in debug and release.
- **Pointer constness:** `const int **` incorrectly became `*const *i32`. Each
  pointer level now retains the correct qualifier. Void-returning callback types
  no longer emit the invalid explicit `void` result spelling.
- **Declaration boundaries:** macro/string contents no longer invent record
  declarations; a valueless macro cannot consume the next source line. C11
  non-prototype `()` declarations/callbacks and unsupported unnamed parameters
  are omitted rather than assigned guessed types. Output write failures produce
  a normal diagnostic instead of a Python traceback.
- **Plain C char:** `std/c.char` was always signed, contradicting the default
  AArch64 Linux ABI. Target files now select `u8` there and `i8` for the other
  supported targets. Explicit signed/unsigned char aliases are unchanged.
  The generator uses `c.char`; ABI probes compare values/signedness with C, and
  AArch64 Linux compilation verifies that 255 is representable. Nondefault C
  char-signedness flags require explicit matching bindings.

Dyn-owned heap allocation remains exclusively arena-based. Pool storage still
comes from caller buffers or arenas. Rebuild affected programs and regenerate
bindings; callers of `free_list_init` must provide at least pointer-aligned
backing and account for rounded slot stride.

## Validation

Fresh validation passed; logs are retained in `build/readiness/preview-logs`:

- `make quality-c`: compiler/editor tests, ASan/UBSan, allocation-failure tests,
  fuzz smoke, 136 frontend fuzz versions and 26 C static-analysis units without
  warnings.
- `make test-libraries`, `make test-readiness` and `projects/validate.sh`:
  SDK/provider regressions, 65 specification fixtures, bounded soak, reproducible
  builds and 112 SDK/project modules. Vulkan ABI checks were skipped because
  development headers are absent. SDL audio ran; GPU hardware was unavailable.
- `tests/aggregate-abi.py --cross`: native Linux execution and Windows, macOS and
  AArch64 cross-link probes in debug and release. Cross-linking is not native
  execution evidence.
- `tests/release-gate.sh` and `benchmarks/compiler-scaling.py --verify`: release,
  reproducibility, compiler scaling, allocation/RSS and editor-latency gates.
- Generated SDK reference and API inventory checks passed. Their declaration
  counts describe inventory, not behavioral coverage.

Previous temporary logs were unavailable after the environment changed; these
results come from rerunning the checks. Package relocation results and checksums
are recorded separately under `build/dist`.

## Release scope

### SDL follow-up

A subsequent report exposed a runtime gap in `projects/stuff-sdl`: it reused a
submitted GPU command buffer, exiting after one frame, and mixed renderer and
GPU presentation. The loop now acquires per frame, uses GPU submission alone,
polls events and reports SDL frame errors. The vendor clear helper now submits
an empty command buffer when a minimized window has no swapchain texture.
`tests/sdl3-loop.py` reproduced the one-frame failure and now verifies three
frames followed by quit, including a missing-texture frame, in debug/release.
It uses SDL contract doubles and is included in project validation. A separate
real SDL run remained alive until a three-second timeout. This is narrow runtime
evidence, not comprehensive GPU or window-system qualification.

### Assessment

This pass found no remaining blocker to a scoped Linux x86-64 developer preview.
That preview should retain `0.1.0-dev`, declare exact system
LLVM/Tree-sitter dependencies, and label other platforms experimental. A stable
release still needs its promised pinned-toolchain/native-provider evidence.
Native Windows/macOS/AArch64 execution, published editor verification, hardware
coverage and stronger security assurances remain separate evidence. The binding
generator is a documented subset, and generated references do not establish
exhaustive behavioral coverage. New syntax and self-hosting are not prerequisites
for a developer preview.
