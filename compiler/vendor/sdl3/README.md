# SDL3 vendor family

All SDL bindings live in this directory. Optional companion libraries have their
own imports so a basic SDL application does not require image/font providers.

| Import | Contents | Native libraries |
| --- | --- | --- |
| `vendor/sdl3` | windows, renderer, events, audio, GPU, surfaces/textures, SDL OpenGL contexts | SDL3 |
| `vendor/sdl3/image` | filesystem/memory image decoding | SDL3_image and SDL3 |
| `vendor/sdl3/mixer` | decoded audio, tracks and offline/device mixing | SDL3_mixer and SDL3 |
| `vendor/sdl3/microui` | optional microui event/render backend | dyn_microui_sdl3, dyn_microui and SDL3 |
| `vendor/sdl3/ttf` | fonts, measurement, UTF-8 text surfaces | SDL3_ttf and SDL3 |

```dyn
use "vendor/sdl3"
use "vendor/sdl3/image" image
use "vendor/sdl3/ttf" ttf
use "vendor/sdl3/mixer" mixer
```

SDL owns native windows, textures, surfaces, devices, streams and fonts. Pair
successful creations with the documented destroy/quit calls. Image and font
rendering return the same `sdl3.Surface` type and use
`sdl3.surface_destroy_owned`. Caller path/decoding buffers remain caller-owned;
Dyn-owned heap buffers come from `std/mem` arenas.

General OpenGL bindings live in `vendor/opengl`; they accept `sdl3.gl_proc` or
another context provider's loader. SDL-specific GL lifecycle functions live here.
Runnable applications remain in the workspace projects directory, and their ABI
and lifecycle tests remain in the shared integration suite.
