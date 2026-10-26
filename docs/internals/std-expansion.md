# Std and vendor expansion before the freeze

Status: planned 2026-10-26. The user chose to land every "gap after the freeze"
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
