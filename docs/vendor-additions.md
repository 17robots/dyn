# Optional native bindings

These are focused initial interfaces, not exhaustive bindings to every upstream
function. Importing a provider links it; applications that do not import it have
no new dependency. Native providers retain their own allocations. Dyn-side output,
paths and work buffers use caller storage or arenas. There is no new Dyn allocator.

All eight packages were exercised on Linux x86-64 in debug and release. Other
platforms still require native library naming, deployment and ABI validation.
Argument-taking examples currently use `std/os/linux`. This is not a cross-platform
release signoff, nor a security audit of upstream libraries.

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

## Build and validation

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

For standalone examples (repository root):

```sh
./build/dyn build projects/regex-example --output build/regex-example
./build/regex-example
./build/dyn build projects/opengl-example --output build/opengl-example
./build/opengl-example
```

Other runnable examples and arguments are listed in `projects/README.md`.

### Local SDL companion builds

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

## Ownership and failure contracts

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

## Sources

- [Tree-sitter C API](https://github.com/tree-sitter/tree-sitter/blob/master/lib/include/tree_sitter/api.h)
- [PCRE2 API](https://pcre2project.github.io/pcre2/doc/pcre2api/)
- [Lua 5.4 manual](https://www.lua.org/manual/5.4/manual.html)
- [libarchive](https://www.libarchive.org/)
- [libcurl easy API](https://curl.se/libcurl/c/libcurl-easy.html)
- [SDL_image](https://github.com/libsdl-org/SDL_image)
- [SDL_ttf](https://github.com/libsdl-org/SDL_ttf)
- [SDL GL procedure loading](https://wiki.libsdl.org/SDL3/SDL_GL_GetProcAddress)
- [OpenGL registry](https://registry.khronos.org/OpenGL/)

## Further provider candidates

The [Odin vendor comparison](audit/odin-vendor-comparison-2026-09-23.md) inventories
the current gaps and proposes an implementation order. These are prospective
additions; each needs its own ownership, ABI, dependency and behavior validation.

SDL_mixer, cgltf, Box2D, microui, LZ4, ENet and miniaudio are now available as
focused optional packages. See [build instructions, ownership and limits](vendor-game-libs.md).

Atlas packing and resizing are available under `vendor/stb/rect_pack` and
`vendor/stb/image_resize`. `vendor/sdl3/microui` supplies the optional SDL UI backend.
See [vendor workflow examples and limits](vendor-game-libs.md).
