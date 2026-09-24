# Dyn example applications

These are small functional programs, not API sketches. Each keeps allocation explicit and uses
procedural standard-library calls. Output consistently goes through `std/io`: `std/terminal`
provides standard-stream adapters, `std/fs` provides file adapters, and `std/net` provides
connection adapters. Protocols and codecs use their nested packages, such as `std/net/http`,
`std/net/websocket`, and `std/encoding/json`; external integrations live under `vendor/`.

- [`memory-tour`](memory-tour/README.md): seven runnable lessons on buffers, heap arenas,
  pointers/slices, rewind/reset, scratch, pools/free lists and growing arenas.
- `field-notes`: interactive task program demonstrating root/sub/frame/scratch arenas.
- `json-check FILE`: arena-backed file input and allocation-free JSON validation.
- `recursive-search DIRECTORY TEXT`: recursive directory traversal and byte search.
- `process-supervisor PROGRAM [ARG...]`: spawn, inherit streams, wait, and report status.
- `http-server` / `http-client`: one-request HTTP/1 loopback pair on port 18080.
- `websocket-server` / `websocket-client`: masked RFC 6455 upgrade and echo pair on port 18081.
- `tar-inspect ARCHIVE.tar`: bounds-checked POSIX tar header traversal.
- `sqlite-example`: explicit C strings, opaque handles, and SQLite foreign calls.
- `raw-terminal`: save terminal state, enter raw mode, process keys, and restore with `defer`.
- `sdl3-example`, `sdl3-audio-example`, and `sdl3-gpu-example`: native SDL3 window,
  queued-audio, and real GPU swapchain-clear lifecycle programs.
- `stuff-sdl`: interactive GPU clear loop. Poll events, acquire a fresh command
  buffer each frame, and present through GPU submission. Submission consumes the
  command buffer; do not reuse it or add an SDL renderer presentation path.

Build and test these examples from this directory with a built or installed SDK:

Build commands require `just`, Python 3, and Bash. Set configuration through
environment variables before the command.

```sh
DYN=/path/to/dyn just
PROJECT=memory-tour DYN=/path/to/dyn just run
DYN=/path/to/dyn just test
just package
```

Vendor packages declare their native dependencies, so importing `vendor/sqlite` or `vendor/sdl3`
links the installed library automatically. Set `DYN_LIBRARY_PATH` for nonstandard library locations;
`--link` remains available as an explicit override. SQLite is skipped only when no shared SQLite library is found. The raw-terminal project receives a pseudo-terminal smoke test when `script` and
`timeout` are available; run it in a terminal and press `q` for interactive testing.
SDL3 examples are skipped when `pkg-config sdl3` is unavailable. SDL owns their
window, renderer, and stream handles; matching `*_destroy_owned` calls release them.

## Optional native-provider examples

`python3 tests/vendor-packages.py` builds and runs these in debug and release.
Missing native libraries are reported as skips; `--require-all` rejects skips.
In the combined workspace, `docs/vendor-additions.md` documents provider setup
and contracts. Standalone builds require the development library matching each
example: Tree-sitter plus its C grammar, PCRE2-8, Lua 5.4, libarchive, libcurl,
SDL_image 3, SDL_ttf 3, or SDL3 with an OpenGL 3.3 core context.

| Project | Demonstration |
| --- | --- |
| `tree-sitter-example` | C grammar traversal, tree copy, edit and incremental reparse |
| `regex-example` | PCRE2 capture offsets, no-match and malformed patterns |
| `lua-example` | Lua 5.4 protected execution, results and stack cleanup |
| `archive-example ARCHIVE` | Stream archive entry names and payloads without extracting paths |
| `curl-example URL` | Bounded HTTP(S) GET into caller storage |
| `sdl3-image-example IMAGE` | File and memory image decode, surface cleanup |
| `sdl3-font-example FONT.ttf` | Font measurement and text surface rendering |
| `opengl-example` | Resizable GL 3.3 core triangle; `--smoke` checks three frames and exits |

Command-line argument examples currently use the Linux process-argument adapter.
The GL test defaults to SDL's offscreen driver; set `DYN_TEST_GL_DRIVER` to test
another driver. An installed SDL alone does not guarantee an available GL context.

## Independent builds and releases

The local justfile owns example builds. `PROJECT=... just build` selects any
example; `PROJECT=... just run argument...` runs it. Default `all` builds the core
examples without requiring optional vendor libraries. `MODE=` chooses debug
instead of the default `--release`; `BUILD` changes the local output directory.
`DYN` may name an installed compiler or an absolute executable path. Without it,
the justfile first tries the sibling workspace/compiler build, then `dyn` on PATH.

`just check` checks every example module. `just test` runs application integration
checks and, when available, the combined workspace's native-provider tests. The
standalone copy explicitly reports that those workspace-only suites are absent.
CLI examples and the integration runner currently target Linux.

`just package` creates `build/dist/dyn-projects-candidate.tar.gz` plus checksum.
It includes example sources, this justfile and validation tools; it requires no
compiler and bundles no native libraries. `just release` additionally builds core
examples. Nothing is published automatically. See the workspace build guide when
running combined compiler/grammar/editor qualification.

### SDL application lifetime

`sdl3-gpu-example` now renders until close; pass `--smoke` for three submissions.
`stuff-sdl` is the minimal continuous GPU loop. Both acquire a fresh command
buffer each frame. Renderer examples redraw after expose/resize events.
`sdl3-audio-example` plays a short quiet tone, flushes and drains the stream with
a five-second timeout, then allows a short device tail before destroying it.
SDL stream drain is not a hardware playback fence; dummy-driver tests establish
lifetime behavior, not audible output. See SDL's [available-byte contract](https://wiki.libsdl.org/SDL3/SDL_GetAudioStreamAvailable)
and [flush contract](https://wiki.libsdl.org/SDL3/SDL_FlushAudioStream).

### Physics, assets, UI, networking and audio

The optional examples `lz4-example`, `cgltf-example`, `box2d-example`,
`microui-example` (headless commands), and `enet-example` run without arguments.
`sdl3-mixer-example` and `miniaudio-example` take a short non-silent WAV file and
exercise offline playback. Build matching providers with `just vendor-libs` from
the workspace, or use installed `dyn-build-vendors`; add the installed `lib` path
to `DYN_LIBRARY_PATH` and `LD_LIBRARY_PATH`. Provider allocations remain foreign;
Dyn context/output buffers use arenas or caller storage.

`stb-example` demonstrates atlas packing and resizing with arena scratch.
`microui-sdl3-example` opens an interactive debug panel; `--smoke` runs five frames.
`audio-playback-example FILE.wav` plays through the default device; append
`--offline` for headless completion checks. See [vendor workflows](../docs/vendor-game-libs.md).

`just browser` builds [browser-canvas](browser-canvas/README.md), a JavaScript-hosted
Wasm module using buffer-backed Dyn arenas. Serve the output directory over HTTP.

`just wasi` builds the WASI argument-printing command. `just browser-video` stages
the pinned FFmpeg Wasm core and builds the worker-based short-clip example.
