# Raw vendor APIs

`dyn-bind-vendors` generates raw Dyn bindings for every current C provider from
its installed public headers. The existing short, hand-written vendor modules
remain the convenient interfaces; generated APIs live in `vendor/<name>/raw`.

Generation is native and configuration-specific. Linux x86-64 has been exercised;
the generator also accepts native Linux AArch64, but this change does not qualify
that platform. These bindings are not cross-platform snapshots. Regenerate after
changing a provider, its feature flags, target, or headers.

## Build

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
selection are in [raw-bindings.json](../compiler/vendor/raw-bindings.json).
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

## Surface

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

## Calling and storage

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

## Optional functions and graphics dispatch

OpenGL and Vulkan commands use explicit typed procedure arguments:

```dyn
// `address` came from the appropriate context/instance/device loader.
// Check availability before casting/calling.
procedure := #cast(gl.Procedure_glClear) address
gl.glClear(procedure, #cast(u32) gl.GL_COLOR_BUFFER_BIT)
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

## Evidence and regeneration

Every generated module contains `coverage.json` and `bridge.c`. The report records
function names, omissions, procedure symbols, provider version/revision when
available, compiler flags, target, ABI fingerprint, and adapter hash. Unsupported
declarations fail generation by default. The overlay-level
`raw-bindings-report.json` records which packages passed.

`tests/vendor-bindings.py` checks aggregate calls and callbacks, packed/union array
fields, bitfields, constants, variable access and stale-layout rejection against
a C oracle. `tests/vendor-raw.py` imports every generated package and makes native
calls in debug and release. The release gate regenerates bindings and runs both
layout validation and import/native-call checks. Layout and smoke checks are not
exhaustive behavioral testing of thousands of upstream functions.

## Executable lifetime examples

Building the `lua` group installs `examples/lua/main.dyn` into the overlay:

```sh
. ./build/raw-sdk/env.sh
"$DYN" run "$DYN_SDK/examples/lua"
```

The example executes a protected Lua chunk, copies a borrowed Lua string into an
application arena, pops the native stack value, then uses only the retained copy.
The native state is closed with `defer`. Both debug and release builds run in the
SDK installation/activation test, including paths with spaces and shell quotes.

The workspace's `projects/memory-tour` also demonstrates persistent state, a pool,
per-request scratch resets and copying escaping results into the correct arena.
No new ownership packages or implicit Dyn heap allocation are introduced.

## FFmpeg (native)

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
Linux; this native package is separate from the [browser FFmpeg integration](../projects/browser-video/README.md), and neither is a finished player/editor.
