# Vendor packages

Packages under `vendor/` bind native C libraries. They are optional: importing a
package links its library, and programs that import none have no native
dependency beyond the Dyn runtime. Each binding covers a focused subset of its
library, and the library keeps its own internal allocations. Dyn-side output,
paths and work buffers use caller storage or arenas as usual.

Linux x86-64 is the platform these bindings are qualified on. Other platforms
need their own library naming, deployment and ABI checks.

There are two layers:

- **Wrappers** such as `vendor/sqlite` or `vendor/sdl3` are small, hand-written,
  Dyn-shaped APIs with documented ownership.
- **Raw bindings** under `vendor/<name>/raw` are generated from the installed C
  headers and expose the full C API. See [raw bindings](#raw-bindings).

## Libraries and utilities

| Package | Provider baseline | Link name | Current surface |
| --- | --- | --- | --- |
| `vendor/tree_sitter` | Tree-sitter runtime compatible with chosen grammar ABI | `tree-sitter` | parser/language selection, UTF-8 parsing, named children, byte ranges, tree copying and edits |
| `vendor/pcre2` | PCRE2 10.x, 8-bit library | `pcre2-8` | compile, match, capture offsets and status |
| `vendor/lua` | Lua 5.4, default 64-bit integer/double ABI | `lua5.4` | text-only protected execution, integer/string results and stack removal |
| `vendor/archive` | libarchive 3.x | `archive` | memory-backed streaming reader, entry names/sizes and payload reads |
| `vendor/curl` | libcurl 7.85+ (`CURLOPT_PROTOCOLS_STR`) | `curl` | synchronous bounded HTTP(S) GET, transport status and HTTP status |
| `vendor/sdl3/image` | SDL_image 3.x plus SDL3 | `SDL3_image`, `SDL3` | filesystem/memory decode to SDL surfaces |
| `vendor/sdl3/ttf` | SDL_ttf 3.x plus SDL3 | `SDL3_ttf`, `SDL3` | font ownership, measurement and UTF-8 text surfaces |
| `vendor/opengl` | current GL 3.3+ core context | none directly | checked function loading, shaders/programs, vertex arrays/buffers, viewport, drawing, pixel readback |

The SDL family lives together under `vendor/sdl3`: core SDL, GPU, audio, surfaces
and SDL GL-context helpers are in the base package; `image` and `ttf` are optional
subpackages. Import only the extensions you need.

OpenGL uses a caller loader; `sdl3.gl_proc` is one option. SDL GL context and shared
surface/texture helpers live in `vendor/sdl3`, so image and font packages reuse the
same cleanup operations. OpenGL does not require Vulkan or the SDL GPU API.

Focused native bindings complement the existing SDK. They are not full upstream
API translations. For the complete selected C declaration surface, generate the
[raw bindings](#raw-bindings). Linux x86-64 native debug/release execution is the initial
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
`share/dyn/vendor/providers.json` in an installed SDK) records immutable upstream revisions.

## Building providers

Install development packages for the providers you use, including unversioned
linker library names and pkg-config metadata. Library filenames vary by platform;
this initial Lua binding deliberately selects 5.4 rather than an unversioned
library that could resolve to an incompatible major/minor ABI.

```sh
just all
just test-vendors
# Qualification run: missing providers/font are failures.
python3 tests/vendor-packages.py --require-all
```

The runner generates PNG and compressed ZIP fixtures, serves HTTP on a private
loopback port, and runs both build modes. It needs no external service. OpenGL
runs three frames under SDL's `offscreen` driver, asserts a red triangle pixel,
and checks the actual core context version/profile. Set `DYN_TEST_GL_DRIVER` for
a desktop driver. Graphics failures are failures, not silently accepted skips.
Set `DYN_TEST_FONT` to a local font if DejaVuSans.ttf is not installed.

Tests check foreign layouts/constants against installed C headers, including
Tree-sitter nodes/edits, SDL colors, curl options, PCRE2 flags and Lua scalar ABI.
The integration test decodes an image, renders font text, uploads a texture and
presents it through an SDL renderer using the dummy video driver.

Results and actual provider versions are written to
`build/vendor-package-results.json`. Missing dependencies are visibly skipped by
the ordinary run; strict qualification requires every package and ABI integration.

Example programs that use these packages live in the Dyn workspace's
`projects/` folder, outside this repository.

#### Local SDL companion builds

This pass tested SDL_image 3.4.6, commit
`f661fa1ad24ab1b81e43662532f9a6a9fcf67ea6`, and SDL_ttf 3.2.2, commit
`a1ce3670aec736ecbf0936c43f2f0cc53aa61e5b`, built from their official repositories.
Sources/build products remain under `build/vendor-deps`; no system installation
was modified. Both were built with system SDL3 and system codec/font dependencies.
The repository does not bundle their source or automatically download providers.

To reproduce with CMake installed, clone those tagged releases and configure:

```sh
cmake -S build/vendor-deps/SDL_image -B build/vendor-deps/image-build \
  -DCMAKE_INSTALL_PREFIX="$PWD/build/vendor-deps/install" \
  -DSDLIMAGE_SAMPLES=OFF -DSDLIMAGE_TESTS=OFF
cmake --build build/vendor-deps/image-build
cmake --install build/vendor-deps/image-build
cmake -S build/vendor-deps/SDL_ttf -B build/vendor-deps/ttf-build \
  -DCMAKE_INSTALL_PREFIX="$PWD/build/vendor-deps/install" \
  -DSDLTTF_SAMPLES=OFF -DSDLTTF_TESTS=OFF
cmake --build build/vendor-deps/ttf-build
cmake --install build/vendor-deps/ttf-build
```

The native test runner discovers this local prefix. For direct builds/runs:

```sh
export DYN_LIBRARY_PATH="$PWD/build/vendor-deps/install/lib${DYN_LIBRARY_PATH:+:$DYN_LIBRARY_PATH}"
export LD_LIBRARY_PATH="$PWD/build/vendor-deps/install/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
```

Native libraries are not bundled in the SDK archive. Redistribution of those
libraries requires following their upstream licenses and those of enabled codec,
font and TLS dependencies. Provider build options determine available features.

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
dyn run path/to/box2d-program
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

## Ownership and lifetimes

Dyn-owned heap storage goes through `std/mem`. Passing an arena for conversion or
output does **not** redirect a native library's internal allocations. No wrapper
silently installs process-global allocator hooks. These policies describe the
shipped bindings, not a guarantee that an entire native dependency is heap-free.

| Provider/path | Allocation and lifetime |
| --- | --- |
| SQLite | Provider-owned database, prepared statements and copied bound values. Finalize statements, then close database. Failed/busy close retains the handle. |
| OpenSSL crypto | Provider-owned temporary EVP contexts/keys, released within each operation. Discard unauthenticated/failed output. |
| OpenSSL TLS | Provider-owned contexts, connections and referenced certificates, with explicit matching releases. Socket ownership stays with caller. Arena parameters hold conversion buffers only. |
| SDL3 | Provider-owned windows, renderers, audio streams and GPU handles; use matching destroy/release functions and retain callback context until native callbacks stop. GPU/device allocations are not ordinary arena storage. |
| Vulkan loader | Procedure lookup returns borrowed native function pointers. Instance/device lifetimes and generated commands remain application-owned. No implicit allocator callback installation. |
| zstd one-shot | Provider may allocate internal contexts. Caller buffers/arena helpers own only input/output/conversion storage. |
| zstd streaming decoder | Uses `ZSTD_initStaticDStream` in caller workspace, with explicit window limits. Workspace outlives context; never pass it to native context-free functions. Advanced ABI is version-sensitive. |

SQLite supports process-global memory configuration with initialization/threading
constraints. OpenSSL also offers global memory hooks; SDL offers memory-function
replacement. A short-lived per-operation arena cannot satisfy those global
lifetimes, reallocations, synchronization, or native subsystem requirements.
Adding hooks would require a separate, explicit application initialization contract.
The current bindings do not claim arena-only provider internals.

Authoritative contracts:
[SQLite configuration](https://www.sqlite.org/c3ref/config.html),
[OpenSSL memory functions](https://docs.openssl.org/3.0/man3/OPENSSL_malloc/),
[SDL memory functions](https://wiki.libsdl.org/SDL3/SDL_SetMemoryFunctions),
[zstd static API](https://github.com/facebook/zstd/blob/v1.5.7/lib/zstd.h).

**Tree-sitter:** destroy parsers and each returned/copied tree separately. Nodes
borrow their tree; reacquire after an edit. Grammar must remain loaded. Parsing
borrows source only during the call. A successful tree can contain syntax errors;
inspect `node_has_error`. When incrementally parsing changed text, edit the old
tree first with matching byte/point coordinates. Edits are caller descriptions,
not source edits performed by the wrapper. Query/capture APIs and grammar loading
are not included yet. Example links a separately installed C grammar.

**PCRE2:** destroy compiled patterns and match-data handles. Match data must be
created for the pattern being used and cannot be shared concurrently. Capture
spans are byte offsets, meaningful only after a successful match; the original
subject must remain alive if you slice it. No-match is a successful operation with
`matched=false`; malformed UTF and provider limits are errors. Compile failures
return provider code and pattern byte offset. This subset has no JIT or custom
match-limit API; do not assume bounded execution for arbitrary hostile patterns.

**Lua:** a state owns its Lua objects and uses Lua's allocator/GC. No standard
libraries are automatically opened. Execute accepts text chunks, leaves one result
on success or one error on Lua failure, and preserves earlier values. Wrapper
preflight errors -1/-2 leave the stack unchanged. Pop values after use; borrowed
strings expire when removed or when state closes. `bytes` accepts existing strings
only, avoiding allocating number-to-string conversion outside protected execution.
The wrapper is not a sandbox or an instruction/time budget. No arbitrary callbacks,
standard-library opening or table-manipulation surface is exposed in this subset.

**Archive:** input bytes remain borrowed until reader destruction. Header names
borrow provider storage; consume/copy before advancing. Reads report bytes/EOF or
a negative provider code. Empty destination is a no-progress success, not EOF.
No extraction is performed, so archive entry names are never treated as trusted
filesystem paths. The example writes entry contents to stdout. Provider warnings
on header reads are exposed as non-success; applications may inspect `code`.

**curl:** initialize before threads and clean up after transfers end. Each request
owns and destroys an easy handle. Destination is caller-owned, never grown; on
failure `written` is partial progress and `capacity_exceeded` distinguishes a full
buffer. URL scratch must fit the NUL-terminated URL. Only HTTP/HTTPS are enabled,
TLS verification remains on, redirects remain off, and positive timeout is required.
Transport success does not mean HTTP success: inspect `http_status`. Existing
environment proxy settings apply. No upload, async/multi or general setopt API yet.

**Images/fonts:** file path buffers are borrowed only during calls. Image decode
consumes input synchronously; successful surfaces need `sdl3.surface_destroy_owned`.
Fonts need `destroy_owned` before balanced TTF quit; use on their creating thread.
Rendered surfaces are independent resources. Uploading a surface copies into an
SDL texture; surface can then be destroyed. Texture must be destroyed before its
renderer. Wrapper validation returns `ok=false`; provider failures may be inspected
through `sdl3.last_error`, but wrapper-only validation does not set an SDL error.

**OpenGL:** make context current before loading and calling. Loaded function table
belongs to that context, not global process state. Failed load returns no callable
table and names the first missing function. Function-table calls use native GL
contracts: inspect compile/link status and `get_error`; passing invalid sizes or
pointers is not made safe by the wrapper. Delete GL objects while context is still
current, then destroy context/window. Apple OpenGL is deprecated; this addition
justs no new macOS graphics support promise.

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

## Raw bindings

`dyn-bind-vendors` generates raw Dyn bindings for every current C provider from
its installed public headers. The existing short, hand-written vendor modules
remain the convenient interfaces; generated APIs live in `vendor/<name>/raw`.

Generation is native and configuration-specific. Linux x86-64 has been exercised;
the generator also accepts native Linux AArch64, but this change does not qualify
that platform. These bindings are not cross-platform snapshots. Regenerate after
changing a provider, its feature flags, target, or headers.

### Build

Install development headers/libraries for the system providers, Clang, and a C
compiler. Build the pinned optional providers first:

```sh
just release vendor-libs
just vendor-bindings

. ./build/raw-sdk/env.sh
python3 tests/vendor-raw.py
```

The full build requires OpenSSL, SQLite, zstd, PCRE2 (8/16/32-bit), libarchive,
libcurl, Lua 5.4, Tree-sitter, SDL3/image/ttf/mixer, Vulkan and OpenGL development
files, plus the providers built by `vendor-libs`. Missing dependencies fail the
build; they are not silently skipped. Clang must see the same native headers as
the C compiler. Set `DYN_BIND_CLANG` to a command with the required sysroot/include
flags if a separately installed Clang uses another sysroot.

`dyn-bind-vendors --list` lists package keys and import paths without building.
After generation, source `env.sh` to select the matching compiler, SDK and native
libraries; existing library search paths are preserved.

Select packages with `VENDOR_PACKAGES='sqlite cgltf'`. The package keys and header
selection are in [raw-bindings.json](../../vendor/raw-bindings.json).
An installed SDK ships the same tools:

```sh
dyn-build-vendors cgltf
dyn-bind-vendors cgltf --output "$PWD/build/raw-sdk"
```

Use `--prefix` and `--sources` consistently when changing their defaults. The
output is an SDK overlay containing the standard library, existing wrappers,
new raw modules, and compiled adapters. Compiler SDK archives ship the generator
and manifest, not a snapshot tied to one machine's library versions. Keep the
generated overlay together with its matching native libraries when deploying.

### Surface

| Provider | Raw import |
| --- | --- |
| FFmpeg core media libraries | `vendor/ffmpeg/raw` |
| SDL3 | `vendor/sdl3/raw` |
| SDL_image / SDL_ttf / SDL_mixer | `vendor/sdl3/image/raw`, `vendor/sdl3/ttf/raw`, `vendor/sdl3/mixer/raw` |
| OpenSSL crypto and TLS | `vendor/openssl/raw` |
| SQLite, zstd, PCRE2, libarchive, curl, Lua | `vendor/sqlite/raw`, `vendor/zstd/raw`, `vendor/pcre2/raw`, `vendor/archive/raw`, `vendor/curl/raw`, `vendor/lua/raw` |
| Tree-sitter, Box2D, cgltf, ENet | `vendor/tree_sitter/raw`, `vendor/box2d/raw`, `vendor/cgltf/raw`, `vendor/enet/raw` |
| microui, miniaudio, LZ4 | `vendor/microui/raw`, `vendor/miniaudio/raw`, `vendor/lz4/raw` |
| stb rect_pack / image_resize2 | `vendor/stb/rect_pack/raw`, `vendor/stb/image_resize/raw` |
| OpenGL / Vulkan | `vendor/opengl/raw`, `vendor/vulkan/raw` |

The SDL microui renderer is a Dyn-specific adapter, already exposed in full by
`vendor/sdl3/microui`; its underlying C APIs are the SDL3 and microui rows above.

The generated surface includes selected public function declarations, dependent
records/typedefs/callbacks, enums (including anonymous enums), evaluable object
constants, and exported variables. Variables use `NAME_address()` accessors.
C names are preserved except Dyn keywords, which receive `c_` prefixes.
`size_t` and pointer-sized integers use Dyn's `usize`/`isize`. Null pointer constants use `rawptr`; non-null integer pointer sentinels
(such as `SQLITE_TRANSIENT`) are zero-argument functions returning `rawptr`.
Other C integer constants retain their C types; explicit casts can be necessary at call sites.

Selected value-taking macros have typed C helpers with their original names.
Currently these cover 31 Lua stack/call/type helpers, 14 OpenSSL protocol/BIO
helpers, four SDL surface/button/version helpers, and FFmpeg AVERROR/AVUNERROR helpers. They call the actual
upstream macros; their native preconditions still apply (for example SDL button
numbers must be 1–32, and Lua stack indices/counts must be valid).

C **function-like preprocessor macros are not generally translated into Dyn
functions**. They have no C ABI and may take types, operators, or token fragments
rather than values. `coverage.json` records `macro_helpers` and `untranslated_function_macros` separately, along with
non-value macros. Use their underlying bound C functions or a small C helper.
Consequently this is full selected **declaration/ABI coverage**, not a claim
that every C preprocessor expression can be pasted into Dyn. Platform-specific
and compile-time-disabled APIs only appear when enabled by the selected headers.
OpenSSL internal names beginning with `_` are excluded.

### Calling and storage

```dyn
use "vendor/box2d/raw" box

fn main() {
  if !box.verify_layout() { #panic("binding/header mismatch") }
  version := box.b2GetVersion()
  if version.major != 3 { #panic("unexpected Box2D") }
}
```

Each package has `verify_layout()`: it checks the generated type sizes,
alignments, field offsets, and matching adapter fingerprint. The builder runs it
in debug and release before installing a package. C static assertions reject
recompiling an adapter against incompatible layouts. These checks cannot detect
an arbitrary incompatible replacement library with a misleading version/soname.

Ordinary records expose fields. Packed records, unions, explicitly aligned
records and bitfields use correctly aligned opaque storage and generated
`Record_field_get` / `Record_field_set` functions. Aggregate field accessors copy
through caller-provided pointers, avoiding unaligned typed pointers. Record
arguments and return values cross a C adapter through pointers, while Dyn sees
ordinary values. Callback declarations retain their native signatures.

Raw APIs keep **upstream C ownership and allocation rules**. Keep arena-backed
arguments alive as long as the native library retains them; run native teardown
before rewinding their arena. Release provider-owned objects with that provider's
matching destructor. Raw foreign allocations do not become Dyn arena allocations.
Where upstream accepts allocator callbacks (for example cgltf/miniaudio), callers
can supply them. The existing stb resize wrapper continues to allocate all scratch
through its arena. Raw stb resize uses a separate upstream-allocation implementation;
the private arena implementation cannot interpose on its symbols.

C strings and byte counts remain explicit. Opaque handles are `rawptr`; sized
records use typed pointers. Public C struct layouts are not an ownership system.

### Optional functions and graphics dispatch

OpenGL and Vulkan commands use explicit typed procedure arguments:

```dyn
// `address` came from the appropriate context/instance/device loader.
// Check availability before casting/calling.
procedure := #cast(gl.Procedure_glClear, address)
gl.glClear(procedure, #cast(u32, gl.GL_COLOR_BUFFER_BIT))
```

Resolve OpenGL commands for the current context, and Vulkan commands through the
correct global/instance/device loader. An extension being declared does not mean
the driver supports it. Keep the loader/context/device alive for every call.

SQLite optional/platform/debug functions, Tree-sitter WASM construction, and
application/provider entry points use the same `Procedure_NAME` pattern. They
remain representable without creating unresolved dependencies when a library was
built without that feature. `coverage.json` lists `procedure_symbols`. Do not
call a null or unavailable procedure. SDL application callbacks and
`OSSL_provider_init` are supplied by applications/providers, not by those libraries.

### FFmpeg

Install development packages for libavformat, libavcodec, libavutil, libswscale,
libswresample, libavfilter and libavdevice, then generate the selected media APIs:

```sh
VENDOR_PACKAGES=ffmpeg just vendor-bindings
. ./build/raw-sdk/env.sh
"$DYN" run "$DYN_SDK/examples/ffmpeg"
```

The example opens a PCM decoder, sends a native packet, reads decoded samples,
and releases frame, packet and codec context in reverse order. Frame sample data
is borrowed until unref/free; copy escaping samples into an application arena.
The integration test separately opens a generated WAV, checks metadata and packet
bytes, reaches EOF, and rejects a missing file. Both execute in debug/release.

This first package covers the headers selected in `raw-bindings.json`, not every
FFmpeg helper header or platform-specific hardware API. It links all seven media
libraries; merely using other vendor packages does not link FFmpeg. Native library
versions are recorded individually in `provider_versions`. Available codecs,
filters and devices depend on the installed FFmpeg build. Generation is native
Linux; this native package is separate from the browser FFmpeg integration. Neither is a finished player or editor.
