# Odin vendor comparison — 2026-09-23

The first seven candidates were subsequently implemented as focused bindings;
see the [current package guide](../vendor-game-libs.md). This comparison records
the assessment before that implementation.

## Scope and evidence

Assessment, not a promise to implement every package. Inspected the official Odin
source tree at revision `a65a8471ed85f22bbfe0cbdb80785580bae6fc3c`. Directory contents are stronger evidence than
the vendor README, which omits some packages present in the tree. This snapshot
is not a claim that every Odin binding is complete or qualified on every target.
[Official vendor tree](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/).

Dyn inventory comes from `compiler/vendor`, `compiler/std`, and
[the local binding guide](../vendor-additions.md). Dyn's existing bindings are
focused interfaces; sharing a provider name does not establish API parity.
No new provider implementation is included in this assessment.

## Existing overlap

Dyn already has SDL3, SDL_image, SDL_ttf, OpenGL, Vulkan, curl and Lua bindings.
Odin has those families too. Odin groups image, mixer and ttf under `vendor/sdl3`;
that is a good organization for Dyn, with optional dependencies still imported
separately. Dyn has no SDL_mixer binding yet.
[Odin SDL3](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/sdl3), [OpenGL](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/OpenGL), [Vulkan](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/vulkan),
[curl](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/curl), [Lua](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/lua).

Dyn also has SQLite, OpenSSL, zstd, PCRE2, Tree-sitter and libarchive providers.
Those names are absent as top-level provider directories in this Odin snapshot;
there is no reason to remove useful Dyn packages to match another SDK.
[Complete Odin directory inventory](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/).

## Missing families

Each row lists actual directories in the pinned Odin tree. These are candidates,
not release requirements.

| Family | Odin packages absent from Dyn vendor | Assessment for Dyn |
| --- | --- | --- |
| SDL companion | [sdl3/mixer](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/sdl3/mixer) | Natural next SDL addition; independently linked. |
| Physics | [box2d](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/box2d), [box3d](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/box3d) | Start with one engine and one tested world/body lifecycle. |
| Model and image assets | [cgltf](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/cgltf), [OpenEXRCore](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/OpenEXRCore), [stb](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/stb) | cgltf adds a clear missing capability. Add individual stb components only for demonstrated format/packing needs. |
| UI and text | [microui](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/microui), [nanovg](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/nanovg), [fontstash](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/fontstash), [kb_text_shape](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/kb_text_shape) | Choose one initial UI approach. Text shaping is a different capability from Unicode decoding or segmentation. |
| Audio and MIDI | [miniaudio](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/miniaudio), [portmidi](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/portmidi), [stb/vorbis](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/stb/vorbis) | miniaudio is useful for programs that want audio without SDL. Avoid adding multiple decoding paths without users. |
| Game networking | [ENet](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/ENet), [ggpo](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/ggpo) | Reliable UDP and rollback warrant separate use cases and tests; ordinary HTTP/TCP support does not replace them. |
| Alternative application frameworks | [glfw](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/glfw), [raylib](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/raylib) | Useful choices for users, but overlap the initial SDL application path. |
| More graphics backends | [wgpu](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/wgpu), [egl](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/egl), [directx](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/directx) | Significant platform, callback, deployment and GPU qualification work. |
| Compression | [compress/lz4](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/compress/lz4), [zlib](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/zlib) | LZ4 offers a new format. A zlib provider should have a measured speed or C-interoperability reason. |
| Platform/ABI surfaces | [darwin](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/darwin), [windows](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/windows), [x11](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/x11), [wasm](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/wasm), [libc](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/libc), [libc-shim](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/libc-shim) | Audit existing std/os and std/c first. A binding cannot create compiler target support. |
| Legacy SDL | [sdl2](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/sdl2) | Defer unless porting an actual SDL2 application requires it. |

Dear ImGui, cimgui and libgit2 are **not directories in this pinned Odin vendor
collection**. They remain possible independent choices, not Odin-parity items.
[Directory inventory](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/).

Some Odin packages are native Odin ports rather than C binding templates. For
example, microui is a port with fixed storage and caller-provided rendering.
A Dyn implementation should deliberately choose an upstream C binding or a
maintained port, rather than mechanically translate Odin code.
[Odin microui README](https://github.com/odin-lang/Odin/blob/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/microui/README.md).

## Suggested order

This order is an engineering recommendation based on Dyn's current SDL focus,
missing capabilities and integration cost, not an upstream guarantee.

1. **SDL_mixer** under `vendor/sdl3/mixer`: loading, playback, stop, completion,
   errors and cleanup. Pin SDL3-era APIs; do not translate SDL2 mixer signatures.
   Odin's current file identifies the 3.2 API with mixer/audio/track handles.
   [Pinned binding](https://github.com/odin-lang/Odin/blob/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/sdl3/mixer/sdl3_mixer.odin).
2. **cgltf**: memory-backed glTF/GLB parsing and validation, accessors and explicit
   cleanup. Keep external resource loading opt-in; the provider's parse operation
   does not load all referenced buffers/images automatically.
   [Pinned loading documentation](https://github.com/odin-lang/Odin/blob/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/cgltf/README.md).
3. **Box2D**: a small 2D physics example is a concrete next application test.
   Choose the exact provider version from its headers rather than inferring ABI
   from a copied README. [Binding files](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/box2d).
4. **One small UI option**: microui fits explicit fixed buffers; use it to build a
   debug panel for the SDL example before growing a full UI abstraction.
   [Fixed-storage and rendering contract](https://github.com/odin-lang/Odin/blob/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/microui/README.md).
5. **LZ4**: bounded encode/decode into caller buffers. Odin exposes the C library's
   destination-capacity APIs; that shape fits Dyn's existing memory model.
   [Pinned LZ4 binding](https://github.com/odin-lang/Odin/blob/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/compress/lz4/lz4.odin).
6. **ENet or miniaudio**, selected by the next real application: multiplayer
   networking or independent audio. Do not make both mandatory SDK dependencies.
   [ENet](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/ENet), [miniaudio](https://github.com/odin-lang/Odin/tree/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/miniaudio).

Defer wgpu until callback lifetimes, surface ownership and the target matrix have
explicit tests. Its own documentation pins a native provider release and describes
a separate browser path; Dyn would need its own implementation and qualification,
not just translated declarations. [Odin wgpu documentation](https://github.com/odin-lang/Odin/blob/a65a8471ed85f22bbfe0cbdb80785580bae6fc3c/vendor/wgpu/doc.odin).

## Avoid duplicate standard-library work

Dyn already provides PNG/QOI, Unicode text support, HTTP, tar/ZIP,
DEFLATE/gzip/zstd interfaces and std/c/platform modules. Inspect their documented
limits before adding competing wrappers. Broad image decoding, shaping, physics,
model loading and reliable UDP are distinct additions; another formatter or
UTF decoder is not justified merely because Odin carries one.
Local sources: `compiler/std/image`, `compiler/std/unicode`, `compiler/std/net`,
`compiler/std/archive`, `compiler/std/compress`, `compiler/std/c`,
`compiler/std/os`. Provider-backed formats may still merit optional performance
or interoperability alternatives with measured evidence.

## Acceptance requirements for every addition

These are proposed Dyn engineering requirements, not descriptions of Odin policy.

- **Ownership:** Dyn-owned heap storage comes only from std/mem arenas. Prefer
  caller buffers or explicit output arenas. Foreign provider allocations remain
  foreign-owned and require their matching destruction function. Document whether
  returned pointers/slices are borrowed, copied or invalidated by later calls.
- **Allocator callbacks:** integrate an arena only when alignment, resize,
  failure, threading and lifetime semantics actually fit. A no-op free callback
  may cause unbounded retention in a long-running provider; do not present that
  as general allocator compatibility.
- **Asynchronous work:** callbacks and user data must outlive registration and
  in-flight work. Stop/join/drain before resetting arenas or destroying devices.
  Audio callbacks must avoid blocking and uncontrolled allocation.
- **Raw versus convenient API:** one canonical ABI definition. Small wrappers
  validate lengths, integer narrowing, embedded NULs and capacities, and retain
  provider error/status information. Do not duplicate shared SDL handle/layout
  declarations in companions.
- **ABI:** pin the provider/header version and build options; verify sizes,
  alignment, offsets, enum values, callbacks and by-value aggregates with C
  header oracles on each supported native target. Name unsupported targets.
- **Build:** optional imports only; reproducible source/dependency setup, explicit
  library lookup and actionable missing-provider errors. Record licenses and
  notices, especially for transitive codecs and redistributed binaries.
- **Behavior:** runnable offline examples plus debug/release tests for success,
  invalid input, insufficient storage, partial initialization, repeated cleanup
  cycles and retained-buffer lifetimes. Hardware-dependent tests require actual
  hardware evidence before claiming support.
- **Release:** integrate strict provider qualification, dependency manifests,
  installed-SDK relocation and performance baselines where relevant. Existing
  release readiness must not be inferred to cover a newly added provider.

The useful target is a small set of well-tested libraries driven by working
programs. Matching every Odin vendor directory is a separate, much larger scope.
