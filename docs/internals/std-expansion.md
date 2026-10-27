# Std and vendor expansion before the freeze

Status: all implementation phases completed locally 2026-10-26; the final
registered regression suite passes. Historical slice notes below remain as evidence; the
closure checklist at the end is authoritative. The user chose to land every "gap after the freeze"
from [std standardization](std-standardization.md#gaps-after-the-freeze), and
more, before the compatibility freeze. Each phase is its own stacked PR on top
of `syntax-statements`. Every new module follows the std rules: caller-owned
storage, arenas first, nil stubs on a miss, and real errors only at the edges.

PNG and QOI encoders already exist (`std/image/png`, `std/image/qoi`), so they
are removed from the gap list.

## Phase 1: platform parity

- `std/terminal` on macOS (termios through the Darwin `ioctl` syscall,
  `TIOCGETA`/`TIOCSETA`/`TIOCGWINSZ`) and Windows (console modes, screen
  buffer size, virtual-terminal input).
- `std/dynlib` on macOS (`dlopen` from libSystem) and Windows (`LoadLibraryA`,
  `GetProcAddress`, `FreeLibrary`, numeric `GetLastError` codes).
- Tests: `tests/platform-parity.py` cross-builds both modules for six targets,
  runs Linux natively and in a pseudo-terminal, and runs Windows under wine.
- Status: done 2026-10-26. Real macOS and Windows console runs are pending CI.

## Phase 1b: systems

Requested 2026-10-26. Lands before GUI, which needs the event loop and text
segmentation.

1. Portable readiness queues over epoll, kqueue and WSAPoll (`std/event`).
2. Job system: fixed workers, task queue over caller storage, wait groups
   (`std/thread/pool`).
3. Signals: interrupt and terminate handling, including the Windows console
   handler (`std/process/signal`).
4. Local time, time zones and calendar formatting (`std/time`).
5. Read-only memory-mapped files (`fs.map`).
6. Unicode grapheme, word and line segmentation (`std/unicode/segment`).
7. Fast non-cryptographic hashes (wyhash) and CRC32 (`std/hash`).
8. Shortest round-trip float formatting and exact parsing (verify `fmt`).
9. Big integers (`std/math/big`).
10. Portable 128-bit SIMD lanes (`std/simd`).
11. Unix domain sockets, UDP multicast, IPv6 checks (`std/net`).
12. Fuzzing support in `std/testing`.

Status: implemented locally 2026-10-26. The twelve systems items now have
registered regression coverage. `std/event` exposes level-triggered readiness,
not asynchronous operation completion. Windows uses WSAPoll, with linear scans;
IOCP requires a separate submitted-operation/buffer-lifetime API and remains
future work. Queue timers, callbacks and GUI message pumping are not provided.
`std/simd` uses existing O3 SSE2/NEON lowering for supported 32/64-bit integer
operations and scalar fallbacks elsewhere; it does not add native vector FFI
or hardware float SIMD. Native macOS and real Windows qualification are pending.

Qualification on 2026-10-26: the registered suite completed across an initial
run and a resumed run after correcting duplicate `CreateEventW` import-table
entries in both Windows runtimes. This is combined evidence, not an uninterrupted
final-state run. The hard-requiring `rv32-soft.py` gate was excluded because
`qemu-system-riscv32` is unavailable; other tests reported their normal missing
system-emulator skips. All remaining registered gates and C regression binaries
passed. Focused networking, event, generic-identity and SIMD tests passed in
debug/release; Linux ARM64/RISC-V64 ran under QEMU, event/SIMD Windows x86-64 ran
under Wine, and both macOS and Windows ARM64 cross-builds passed. Unix/IPv6 and
multicast execution on Windows is not established by those cross-builds.
Formatting checks for the three new/changed packages and std lint also passed.

The generic-symbol collision found during event integration is fixed by hashing
canonical nominal and compound type identities instead of diagnostic names.
The regression covers same-named structs, enums and distinct types from different
packages, including pointers, arrays, slices and function types.

## Phase 2: embedded helpers

Move the board helpers out of `tests/bare-metal/board_*.dyn` into std beside
`std/mmio`: `std/embedded/uart`, `std/embedded/timer` (CLINT/mtime, SysTick)
and `std/embedded/interrupt` (mtvec/NVIC enable, disable and critical
sections). Board tests then use std.

## Phase 3: portable media and data

Pure Dyn, no platform calls:

- Fonts: TrueType parsing and an antialiased glyph rasterizer
  (`std/font`), plus a glyph atlas packer.
- Text layout: line breaking, kerning and simple shaping for Latin text
  (`std/text/layout`). Complex scripts stay in vendor (HarfBuzz).
- Immediate-mode UI core: widgets that emit a draw-command list
  (`std/ui`). Rendering backends live in vendor.
- More image codecs: BMP, TGA, PPM/PGM read and write; GIF and baseline
  JPEG decode.
- Audio formats: WAV read and write.
- Data formats: TOML, CBOR, MessagePack, protobuf wire format.

### GUI foundation progress (2026-10-26)

The first GUI slice is implemented locally: `std/ui` emits caller-arena-owned
rectangle and text commands with clip snapshots, stable IDs, pointer capture,
forward keyboard focus, buttons, checkboxes and integer sliders. `std/ui/software`
executes those commands into caller RGBA storage using a caller-supplied bitmap
glyph callback. This provides a complete headless rendering path without SDL or
other native dependencies. `tests/ui-demo` produces an inspected 480x240 PNG.

`tests/ui-results.py` checks interaction sequences, clipping, extreme coordinates,
text ownership, straight-alpha blending, glyph coverage, UTF-8 recovery, invalid
inputs and frame lifecycle errors. Debug/release and emulated Linux ARM64,
RISC-V64, Windows x86-64, and WASI execution pass; both macOS targets and Windows
ARM64 cross-build. The PNG example produces identical bytes in debug/release.
The WASI execution test exposed stale unreachable bodies after O3 inlining;
Wasm now filters emitted functions by liveness. A separate O2/O3 regression checks
allocation, exports, initialization and indirect callbacks.

This does not complete the GUI phase: TrueType/font atlas work, general text
layout, native windows/input and GPU renderers remain open. Software text currently
uses code-point advances and newline handling without kerning, wrapping or shaping.

Qualification completed on 2026-10-26: focused UI and O2/O3 Wasm regressions
passed, as did the browser/WASI, Wasm linker, assembly and semantics gates using
the rebuilt release compiler. The broad registered regression run completed
across an initial run and a resumed run after formatting the nested software
renderer module explicitly. This is combined evidence, not an uninterrupted
final-state run. `rv32-soft.py` was excluded because `qemu-system-riscv32` is
unavailable; other missing system-emulator cases reported normal skips. All
remaining gates and C regression binaries passed. UI source and example formatting
and std lint pass. Real macOS and real Windows GUI execution remain unverified.

### Initial TrueType font slice (2026-10-26)

`std/font` now loads single SFNT TrueType faces with cmap 4/12, horizontal metrics
and short/long loca, rasterizes simple quadratic outlines without hinting, and
packs caller-sized alpha atlases. `std/font/ui` connects direct or cached glyphs
to the existing software renderer. The cache renders without new allocations.
The font face borrows input bytes; rasterized bitmaps and atlases are arena-owned.

Synthetic-font tests verify solid rectangles, oppositely wound holes, coverage
against an analytic parabola, cmap/loca variants, truncation/mutation safety,
failure rollback, atlas packing and rendering equivalence. The optional Liberation
Sans example produces identical PNG output in debug/release and was inspected.
No system font bytes are copied into the repository. Focused font and UI gates
pass; font tests cross-build macOS and Windows ARM64 and execute on Linux,
emulated ARM64/RISC-V64, Wine and WASI where available.

At this initial stage, composite glyphs returned `Unsupported`; the composite
pass below supersedes that limitation. Hinting, collections, CFF, variable-instance
selection, kerning, shaping and general text layout remain open. Native windows
and GPU renderers are still pending. See the std guide for resource limits.

Focused qualification also passes the existing UI, image-result and std memory
contract gates in debug/release, plus the formatter and std lint. The full broad
regression suite was not rerun for this isolated font slice. Native macOS and
real Windows font execution remain unverified; cross-builds and Wine are distinct
from native platform qualification.

### Composite TrueType glyphs (2026-10-26)

The shared outline reader now expands composite glyphs before rasterization.
It supports byte/word XY offsets, ordinary contour-point attachment, independent
scale and 2x2 transforms, nested components, and horizontal metric selection.
Cycle detection and shared point/node/depth budgets bound untrusted graphs.
Failure paths rewind the entire arena allocation, including empty composites.
Phantom-point attachment and non-diagonal or negative-horizontal-scale selected
metrics remain explicit `Unsupported` cases. Grid fitting and hint programs are still omitted.

`tests/font-composites.py` compares 19 composite glyphs with independently
flattened outlines at two sizes, including curves, bearings, metric origins,
mirrors, shear, scaled offsets, attachment and empty glyphs. Fifteen malformed,
cyclic, unsupported and budget cases verify errors and allocation rollback.
Debug, release O2/O3, emulated native and WASI checks cover the same cases.
The existing font/UI tests also pass, and the inspected Liberation Sans PNG demo
now includes “Café Å ñ ü Ç”. General text layout, kerning, native windows and
GPU renderers remain open.

Focused qualification passes the existing font, UI and arena-memory contract
regressions, formatter and std lint, alongside the new composite gate. Synthetic
composite checks execute in debug and release O2/O3, under ARM64/RISC-V64 QEMU,
Wine x86-64, and WASI; macOS and Windows ARM64 cross-builds pass. The full broad
regression suite was not rerun for this isolated font change. Real macOS and
real Windows execution remain separate qualification work.

## Phase 4: vendor graphics and windowing without SDL

- `vendor/window`: native windows and input for X11, Wayland, Win32 and
  Cocoa, behind one small API.
- Renderers for `std/ui` draw commands on OpenGL and Vulkan, both of which
  already have bindings in `vendor/`.
- New bindings where useful: WebGPU (wgpu-native), Metal, Direct3D 12,
  FreeType, HarfBuzz, GLFW, raylib and Dear ImGui (cimgui).

## Phase 5: native crypto

Replace the OpenSSL-backed `aes`, `aead`, `signature`, `exchange` and
`certificate` modules with Dyn implementations: AES-GCM, ChaCha20-Poly1305,
X25519, Ed25519, ECDSA P-256 and X.509 validation. Every primitive needs
published test vectors and a constant-time review. Then audit all of
`std/crypto`. OpenSSL stays in `vendor/openssl`.

## Exit

All phases merged, docs updated, qualification rerun. Then record the freeze
and start the two-preview clock.


## Current implementation checkpoint (2026-10-26)

This checkpoint supersedes earlier pending statements about layout, kerning and
embedded helpers. Unicode text layout, TrueType legacy pair kerning and positioned
UI glyph commands are implemented and tested. UART/CLINT/SysTick/interrupt helpers
are in std, and all three board fixtures use them. Actual system-QEMU runs now
pass RV32, RV64 and Cortex-M debug/release, including nested critical sections,
arena allocation and panic cleanup. Packages were extracted under `/tmp`, without
changing the host installation. These runs found and fixed a pre-existing RV64
allocator alignment instruction that silently encoded an invalid immediate;
the assembler now rejects out-of-range immediate encodings against Clang oracles.

WAVE, PPM/PGM, protobuf wire format, MessagePack and CBOR are implemented with
registered host, emulated and cross-target tests. Formats still in progress are
BMP/TGA, GIF/baseline JPEG and TOML. OpenGL has the texture/blending/scissor API
needed by the UI renderer; native windows and GPU backends remain in progress.

AES-256-GCM and ChaCha20-Poly1305 now use pure Dyn implementations. The AEAD facade
no longer imports OpenSSL and passes native, cross-target and emulated contract
checks. NIST/RFC goldens, independent integer/EVP oracles, boundary lengths,
tampered tags/AAD/nonces/keys/ciphertext, overlap checks and allocation rollback
are covered. Poly1305 also covers the p-1/p/p+1 reduction boundaries, zero-r keys,
all streaming splits and bytewise updates. This does not close the crypto phase:
curve algorithms, X.509 validation and the complete constant-time audit remain
in progress. No compatibility freeze or preview clock has started.


## Implementation closure and release checklist (2026-10-26)

All five implementation phases now have code, focused tests and independent
review. The profile limits below are deliberate API boundaries, not claims of
complete format/PKIX/graphics feature parity.

| Area | Local implementation and proof | Remaining qualification |
| --- | --- | --- |
| Platform/systems | Terminal/dynlib parity and all twelve systems items; registered tests | Real macOS/Windows platform paths |
| Embedded | UART, CLINT/SysTick, vector/critical-section/NVIC helpers; RV32/RV64/Cortex-M QEMU debug/release | Physical boards |
| Text/UI | TrueType simple/composite atlas, legacy pair kerning, Unicode/NFC Latin layout, software/positioned UI | Complex paragraph layout is application/vendor policy |
| Portable formats | WAV, BMP/TGA/PPM/PGM, first-frame GIF, baseline JPEG, TOML 1.0, CBOR, MessagePack, protobuf wire | Broader format profiles are explicit unsupported cases |
| Native windows/GL | X11/GLX 3.3 core, Wayland/EGL, Win32/WGL, Cocoa 4.1; actual X11/Wayland/Wine GPU/software oracles | Native Cocoa SDK/runtime and real Windows CI |
| Vulkan | Actual GPU compute UI renderer with exact straight-alpha RGBA oracle and bounded resources | Native bridge execution outside Linux; WSI/swapchains are not provided |
| Font providers | Dynamic FreeType raster/adapter and HarfBuzz run shaping; C raster/shaping and Windows/Unix layout oracles | Native provider execution outside Linux |
| Crypto | Native AES-GCM/ChaCha-Poly, X25519/Ed25519/P256/SHA512, explicit Ed/P256 X509 validation; vectors, malformed-input/alias gates | Not machine-wide constant-time certification or full browser PKIX |

The [native crypto review](native-crypto-review.md) covers every std crypto source
and selected O2/O3 emitted mask/comparison sites on x86-64, AArch64 and RISC-V.
It records bounds and limitations, including RFC6979 rejection retries. The audit
also fixed older HMAC oversized-key handling, KDF length overflow and borrowed-key
corruption from mutable overlap, plus the SHA256 block-loop overflow expression.
Native cipher, signature and exchange facades no longer import OpenSSL. TLS keeps
its separate vendor-backed handshake and trust-store behavior.

Independent review additionally fixed soft-hyphen/kerning/clip issues, invalid
JPEG Huffman/padding acceptance, OS/2 BMP header misclassification, TOML leap-second
rejection, GL oversized uploads/state/resource failures, Cocoa multiwindow input
routing and HarfBuzz non-null empty-object allocation failure handling.

The macOS ARM64 and Windows x64 compiler-host workflows now run a native expansion
probe (16 projects in debug/O2/O3) and native window/UI qualification. Windows
provisions Mesa llvmpipe/WGL from MSYS2 and deploys both required DLLs alongside
test executables. The host probe's 48 Linux executions pass; YAML syntax is checked.
Configuring these jobs is not evidence that they have executed on native hosts.

Release work remains distinct from local implementation: publish/review/merge,
native platform CI, physical-board qualification where required, then explicitly
record the compatibility freeze and run the two-preview stability period. No
freeze or preview clock has started in this local implementation pass.

Final full-suite evidence is recorded in [the expansion qualification record](qualification-20261026-expansion.md).

## Surrounding-text correction follow-up

Added `std/text/edit`, ordered replacement assembly, and box textbox revision
checks. Native Wayland/Cocoa snapshots carry selection, revision and change
cause. X11 and Windows explicitly reject this capability while retaining basic
IME input. Qualification covers transactional Unicode edits, stale revisions,
native callback/protocol contracts and the seven-argument C ABI. Cocoa callback
runtime checks require macOS. Existing aggregate-input examples remain limited
to preedit and committed text; SDL/SDL_ttf replacement in DNA remains pending.
