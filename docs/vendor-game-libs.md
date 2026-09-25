# Optional game, asset, UI and audio providers

Focused native bindings complement the existing SDK. They are not full upstream
API translations. For the complete selected C declaration surface, generate the
[raw vendor APIs](vendor-raw-bindings.md). Linux x86-64 native debug/release execution is the initial
qualification; other operating systems need adapter builds and native tests.

| Import | Pinned provider | Implemented surface | Ownership |
| --- | --- | --- | --- |
| `vendor/sdl3/mixer` | SDL_mixer 3.2.4 | offline stereo float mixing, default device, memory decode, tracks, play/stop/status | SDL owns mixers/audio/tracks; tracks die with their mixer; audio is separately released |
| `vendor/cgltf` | cgltf 1.15 | glTF/GLB parsing, explicit external buffer attachment, mesh/material traversal, transforms and accessor/index reads | provider owns model; input bytes stay alive until destruction |
| `vendor/box2d` | Box2D 3.1.1 | worlds, bodies, boxes/circles, distance joints, contact begin/end events and AABB queries | provider owns allocations; integer generation-checked IDs; world owns bodies/shapes |
| `vendor/microui` | microui commit in manifest | windows, labels, buttons, mouse input and draw-command iteration | context is arena-backed, no provider heap; commands/text borrow until next frame |
| `vendor/lz4` | LZ4 1.10.0 | bounded raw-block compression/decompression | input/output caller-owned; no overlapping buffers |
| `vendor/enet` | ENet 1.3.18 | configurable numeric-IP listener/client, 1–255 reliable channels, received channel and disconnect reasons | hosts/packets provider-owned; peers borrow host lifetime; received packets require release |
| `vendor/miniaudio` | miniaudio 0.11.23 | memory decoding, offline/default-device engine, sound handles with play/stop/rewind/volume/completion | context arena-backed; provider owns internal storage/workers; close before resetting arena |
| `vendor/stb/rect_pack` | stb rect_pack 1.01 | bounded atlas packing with partial-fit reporting | caller rectangles; temporary arena storage, rewound on return |
| `vendor/stb/image_resize` | stb image_resize2 2.18 | packed u8 image resizing, linear/sRGB | caller pixels; temporary arena storage, rewound on return |
| `vendor/sdl3/microui` | microui + SDL3 | mouse/wheel event translation and rectangle/text/icon/clip rendering | borrows UI context and SDL renderer |

The authoritative manifest (`compiler/vendor/providers.json` in source;
`share/dyn/vendor/providers.json` in an installed SDK) records immutable upstream revisions. See the [API research](audit/vendor-native-api-notes-2026-09-23.md)
for SDL_mixer, Box2D and ENet header contracts, and the
[Odin comparison](audit/odin-vendor-comparison-2026-09-23.md) for the selection rationale.

## Build and use

```sh
# Source checkout; optional, separate from building the compiler:
just vendor-libs
# Or select providers:
VENDOR_PACKAGES='stb cgltf box2d enet miniaudio microui-sdl3' just vendor-libs

# Installed SDK includes the same builder and adapter sources:
dyn-build-vendors cgltf --prefix "$PWD/build/vendor-deps/install"

export DYN_LIBRARY_PATH="$PWD/build/vendor-deps/install/lib"
export LD_LIBRARY_PATH="$PWD/build/vendor-deps/install/lib"
export PKG_CONFIG_PATH="$PWD/build/vendor-deps/install/lib/pkgconfig"
dyn run projects/box2d-example
```

Building requires Git, a C compiler, make and CMake. SDL_mixer requires SDL3 3.4+
development files. The builder fetches only pinned commits, installs to the
chosen prefix, and retains provider license files and source revisions under
`share/dyn-vendor-licenses`. It does not install into the system prefix by default.
The native providers/adapters are optional external shared libraries, **not
bundled into the compiler SDK archive**. Ship the matching libraries and notices
when distributing an application that uses them.

`dyn-build-vendors` builds small adapters as `libdyn_cgltf`, `libdyn_box2d`,
`libdyn_microui`, `libdyn_microui_sdl3`, `libdyn_stb`, `libdyn_enet`, and `libdyn_miniaudio`. These compile against the
actual pinned C headers. Dyn does not duplicate large/private provider structs.
The Box2D adapter uses upstream integer-ID helpers; the UI/audio adapters report
context size/alignment and place wrapper state in the caller's arena. LZ4 and
SDL_mixer use their normal shared-library names. Changing a provider version or
build configuration requires rebuilding the corresponding adapter.

The builder stages two small upstream correctness fixes without modifying source
checkouts: microui command-buffer/base alignment and padded command sizes;
stb scalar byte-buffer copies/stores use alignment-safe memory operations while
retaining SIMD. Installed notices record these modifications. Both are checked
with AddressSanitizer and UndefinedBehaviorSanitizer.

## Memory and lifetime rules

Dyn-owned heap memory still comes only from `std/mem` arenas. Stack slices work
for LZ4 and PCM output; buffer-backed arenas work for UI/audio contexts. Native
providers retain their own allocation policies and matching destruction calls.
Resize uses a private synchronous arena callback; temporary allocations are
reclaimed together when the call returns. No public general allocator or
ownership-transfer package is added.

- Close explicit miniaudio sound handles before their engine. Stop preserves
  playback position; rewind seeks to the start. Query ended for natural completion.
- Do not reset the arena containing a miniaudio context until it is closed.
  Close joins/stops provider work and releases provider storage; it does not
  reclaim arena space. Rewinding the arena is a separate caller decision.
- Atlas packing and resizing reclaim scratch allocations before return, including
  failure. Source/destination/rectangle buffers must not overlap scratch storage
  allocated by that call. Existing allocations below its entry mark are valid.
- A miniaudio decoder retains the original input. cgltf GLB buffer views can
  also borrow the original bytes. Keep them unchanged through destruction.
- SDL_mixer memory loading predecodes synchronously; the input slice can then be
  reused. Destroy tracks, audio, mixer, then quit; do not also destroy tracks
  after their mixer has already destroyed them.
- ENet `send` copies source bytes. Its private packet transfers to ENet only on
  successful send. Received packet bytes expire when `packet_destroy` is called.
  Destroy hosts before `quit`; stop using their borrowed peers first.
- UI commands expire at the next `begin`. Consume/copy them before building the
  next frame. UI state is fixed-capacity; the adapter rejects excess command
  work before overflowing its provider command buffer.

Provider handles remain unsafe to fabricate or use after destruction. Generation
checks on Box2D IDs do not turn other raw provider pointers into checked handles.

## Current limits

SDL_mixer's supplied build recipe disables optional codecs: built-in WAVE, AIFF,
VOC and AU remain available, with PCM WAVE tested. Both audio adapters expose
48 kHz interleaved stereo f32 offline output. Miniaudio default-device output is
available but actual audible playback/backend coverage remains external evidence.
SDL's default-device creation is exercised with the dummy audio driver.

cgltf never resolves external paths automatically. Use `buffer_uri`/`buffer_size`,
load each external resource under application policy, then `attach_buffer`.
Attached bytes are borrowed through model destruction. `load_embedded` rejects
any unresolved external buffer before loading data URIs/GLB data; already attached
buffers are skipped. Nodes expose mesh indices and world transforms; primitives
expose attributes, indices, topology and material indices, with RGBA base factors.
Queries returning signed indices use -1 for absent/invalid. Sparse accessor reading and glTF writing are outside this
surface. Apply input-size limits in the application before parsing untrusted data.

Box2D accepts finite gravity/geometry, positive half-extents, nonnegative density,
steps up to one second and 1–64 substeps. Use a fixed small timestep in practice.
Distance joints connect body origins. Enable contact events on shapes, then read
begin/end events immediately after stepping and before world mutation. AABB
queries return broad-phase candidates; total reports truncation when output is
short. This does not promise deterministic simulation across platforms.

The microui core supplies commands independently of SDL. `vendor/sdl3/microui`
renders them using SDL rectangles, lines and built-in debug glyphs. Feed SDL
events before `begin`, render after `end`, then present. Rendering consumes the
command iterator and restores SDL clip, blend and draw-color state. Text metrics
are fixed 8×16 monospace **bytes**, with ASCII debug glyphs, not Unicode shaping. Window/input coordinates
are limited to ±1,000,000 and positive window dimensions to 1,000,000. Titles and
widget labels are limited to 4096 bytes. Windows cannot nest through this initial
adapter; each successful window begin needs a matching end before ending a frame.

LZ4 operates on raw blocks, not LZ4 frames. The caller must know the output bound
and check returned status. Failed compression/decompression may alter output.
ENet’s `listen_owned` helper remains loopback/one-channel. `listen_at_owned`
accepts numeric IPv4, including `0.0.0.0` for all interfaces. Extended constructors
and `send_channel` support 1–255 channels; received events include channel IDs. Payloads sent through the helper are capped at 1 MiB.
Reliable UDP is not encryption or authentication. Graceful disconnect is
asynchronous: keep servicing until Disconnected or an application deadline.
The receiving peer sees the supplied disconnect reason in event data.

stb rectangles use integer dimensions 1–32768 without rotation; `packed` marks
individual successes when the atlas is too small. Resizing supports tightly packed
1–4 channel u8 pixels with dimensions 1–32768 and at most INT32_MAX bytes per
image. RGBA is straight alpha. Failed operations may alter output; reject overlapping
input/output. Scratch exhaustion returns failure without leaking arena space.

## Examples and validation

`lz4-example`, `cgltf-example`, `box2d-example`, `microui-example`, and `enet-example`
run without arguments. `stb-example` checks packing/resizing with caller storage. `cgltf-example FILE.glb` additionally reads a GLB model
containing an initial VEC3 accessor `[0, 1, 2]` for its regression assertions.
`sdl3-mixer-example FILE.wav` and `miniaudio-example FILE.wav` require a short,
non-silent audio fixture; the runner generates one automatically.

```sh
# Interactive UI: close window to exit. --smoke runs five frames and clicks a button.
dyn run projects/microui-sdl3-example
# Real default-device playback; exits at EOF, bounded to 60 seconds.
dyn build projects/audio-playback-example --output build/audio-playback
./build/audio-playback path/to/short.wav
# Headless equivalent uses offline mixing and checks nonzero output.
./build/audio-playback path/to/short.wav --offline

python3 tests/vendor-extra.py --require-all
just test-vendors
# Requires the pinned/staged sources produced by vendor-libs:
python3 tests/vendor-sanitize.py
```

The runner checks debug/release behavior: bounded and malformed LZ4 blocks,
embedded JSON glTF and binary GLB, rejected external buffers, a falling box that
rests on the ground, stale body handles, balanced UI frames and exhausted command
iteration, reliable UDP loopback with a deadline, invalid audio, arena rollback,
nonzero decoded/mixed samples, EOF silence, stop and repeated cleanup.
The suite also checks atlas overlap/partial fits, short scratch, resized colors,
external glTF buffers and mesh/material/index traversal, circle contacts, distance
joints, truncated queries, multi-channel traffic and graceful disconnects. SDL’s
software renderer is tested against actual surface pixels, event translation,
button clicks and restoration of caller renderer state.
Results and provider versions go to `build/vendor-extra-results.json`.
Missing providers fail under `--require-all` or `DYN_REQUIRE_ALL=1`. The release
check includes this suite. Passing offline audio does not establish audible output.
