# Std expansion qualification — 2026-10-26

Status: the uninterrupted final-code registered suite passed. One optional
Unicorn branch was skipped in that environment and then passed separately. This
record distinguishes local execution, cross-builds, emulator runs and unexecuted
native CI.

## Source and environment

Implementation code is frozen at local revision `ff9c3536`; later documentation
commits do not change the tested code. The compiler is the rebuilt independent
release compiler. Host: Linux x86-64, with user-mode QEMU, system QEMU, Wine, Node
WASI, X11/Wayland, desktop OpenGL and Vulkan available. System QEMU packages were
extracted into `/tmp/dyn-qemu`; no system installation was changed.

Release compiler SHA256: `b281ea7e64900dcf4bd306ec6240193cc5025f82c474dce3bc5f3e49ba245618`.

The [crypto review](native-crypto-review.md) records per-source hashes, the
emission driver and six O2/O3 object hashes. Third-party algorithm provenance is
recorded in `THIRD_PARTY_NOTICES.md`.

## Full registered suite

```sh
PATH=/tmp/dyn-qemu/bin:$PATH python3 tests/run.py
```

Result: **PASS**, ending with `PASS standalone compiler regression suite`.
The full run includes all registered Python gates and C regression binaries.
There were no system-QEMU skips. Its one optional Unicorn skip is closed by the
separate successful CPU run below. Expected failure-injection diagnostics in the
log are passing negative tests, not unhandled suite failures.

Full log SHA256: `8cad0bc91b5f332889f71d8d7c8b4fe83a0d0b5844894425f8edf6afb856987b`.
The final native-host probe also passes all 16 projects in debug/O2/O3 (48 runs).
Earlier initial/resumed runs are not counted as an uninterrupted final-state
pass. They exposed transitional provider-mock assumptions and unformatted active
agent files; both were corrected before this final code freeze.

## Focused evidence

- Text layout, UI, fonts/kerning/composites and Wasm aggregate temporaries pass
  debug/release/O3 and available emulated/WASI execution and cross-target checks.
  The rebuilt Liberation Sans PNG demo was inspected; font bytes are not bundled.
- Embedded UART/timer/interrupt gates pass. Actual system QEMU executes RV32,
  RV64 and Cortex-M debug/release, including nested interrupt state, arena
  allocation and panic cleanup. The RV64 allocator alignment regression and
  RISC-V immediate validation have Clang-oracle coverage.
- `tests/nucleo-profile.py` passes its layout/overflow checks. The main full
  suite lacks the optional Unicorn module; a separate disposable environment
  executes and passes startup, dirty-RAM initialization, arena and UART checks:
  `uv run --no-project --with unicorn python tests/nucleo-profile.py`.
- BMP/TGA/GIF/JPEG pass 436 golden/truncation/mutation cases in debug/release,
  independent FFmpeg/libjpeg comparisons, 28 cross-builds and 12 available
  ARM64/RISC-V/WASI runtime probes. Codec profile limits are in the std guide.
- TOML passes 850 corpus/oracle cases and five dedicated RFC3339 lexeme cases,
  debug/release, seven cross-builds and ARM64/RISC-V/WASI execution. The optional
  official toml-test corpus was pinned at
  `ff49d109861c1ad25af53f687f2aef19ab650600`; year0000/leap-second cases are kept
  separate from Python datetime limitations.
- WAV, PPM/PGM, protobuf, MessagePack and CBOR have independent goldens,
  malformed-input, overflow/ownership and native/emulated/WASI coverage.
- Native AES-GCM/ChaCha-Poly, Poly1305, X25519, Ed25519, SHA512 and P256 pass
  published vectors and independent saved EVP/integer/hashlib oracles, native
  debug/O2/O3, seven cross-builds and available QEMU/Wine/WASI execution.
  X509 exercises mixed Ed/P256 trust paths, exact pins, validity, DNS/wildcard/IP,
  constraints, malformed DER and strict public-key validation.
- HMAC/KDF audit regressions pass independent derivation vectors, overlapping
  valid slices, untouched-output checks and forged oversized lengths. Raw ChaCha
  counter exhaustion rejects a forged maximum-size span before reading it.
- Additional bare-metal crypto proof cross-builds all four RV32/Thumb hard/soft
  targets in debug/release. Release QEMU executes AES-GCM, ChaCha-Poly, Poly1305,
  X25519, Ed25519 and SHA512 on all four. P256 public/sign/verify compiles but its
  guest smoke exceeds a 60-second budget; that guest runtime remains inconclusive.
  Native/emulated 64-bit and WASI P256 tests pass separately.
- Native windows/OpenGL pass GPU-versus-software pixel comparisons on actual
  X11 and Wayland and under Wine/WGL in debug/O2/O3. Cases include hostile GL
  state, clipped/oversized coverage, malformed callbacks, injected resource/GL
  failures and actual asynchronous GLX error recovery. Windows bridge C compiles
  for x64/ARM64; six-target Dyn object generation passes.
- Vulkan compute renders exact software-reference bytes on the actual GPU,
  including transparent alpha, copied borrowed glyphs, padded rows, buffer reuse,
  budgets and errors. Six-target Dyn objects pass; this is not WSI presentation.
- FreeType/HarfBuzz pass independent C bitmap/metrics and full Latin/Arabic
  shaping oracles, shaped Arabic rendering, ownership and empty-object OOM
  regressions. FreeType public-record layouts match actual C headers for Unix
  long64 and Windows long32, including Windows x64/ARM64 cross-compilation.
- The native host probe has 16 fixture projects in debug/O2/O3. Native macOS/
  Windows jobs now run it and window/UI gates; Windows provisions Mesa/LLVM and
  deploys both WGL DLLs. Workflow YAML syntax and job names are checked locally.
  Configuration is not a claim that remote native jobs ran.

## Remaining release qualification

Native Cocoa SDK compilation/execution, real Windows execution and native font/
Vulkan provider execution outside Linux remain unverified here. Physical-board
execution remains unverified. There is no all-processor constant-time claim;
source and selected emitted-code review boundaries are explicit in the crypto
record. P256 reference arithmetic favors portability over embedded throughput.

Publication/review/merge, native CI and the compatibility freeze/two-preview
period are separate milestones. No freeze or preview clock has started.

Local evidence is retained under `build/std-expansion-qualification/`; it is not
packaged as released SDK proof or represented as native hardware qualification.
