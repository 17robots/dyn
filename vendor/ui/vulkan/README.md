# Vulkan compute UI renderer

This adapter executes ordered rectangle, text and positioned-glyph commands on a
Vulkan compute queue and returns caller-owned straight-alpha RGBA pixels. Integer
compositing matches `std/ui/software` exactly, including transparent destinations.
Glyph callback coverage is cropped and copied before another callback can replace
it. The native bridge owns its device, pipeline and reusable mapped storage buffer.

`open(renderer, limits)` creates the device. `render(renderer, scratch, surface,
commands, font)` is synchronous: it preserves existing destination pixels, waits
for GPU completion, and writes the result into `surface`, preserving row padding.
Use a temporary caller arena for scratch, resettable after rendering; font callbacks
must not retain new cache entries in that scratch arena. `Limits` bounds draw count
and copied coverage. Hardware storage-buffer/dispatch limits return `Capacity`.
Serialize access to each renderer and call `close` when finished.

This is a headless renderer, with no Vulkan surface or swapchain ownership and no
Vulkan WSI presentation adapter. The OpenGL renderer provides native-window
presentation. Compute work currently visits each command for each pixel; this
prioritizes predictable correctness over large-scene throughput.

```sh
python3 vendor/ui/vulkan/native/build.py \
  --include build/vendor-deps/install/include \
  --output build/ui/libdyn_ui_vulkan.so
dyn build example --link build/ui/libdyn_ui_vulkan.so
```

Building requires `glslangValidator`, Vulkan headers and the loader library. On
macOS use `libdyn_ui_vulkan.dylib` with a Vulkan/MoltenVK development environment;
on Windows use `dyn_ui_vulkan.dll` and link its generated `libdyn_ui_vulkan.dll.a`.
Portability enumeration/subset extensions are enabled when advertised.

`tests/vulkan-ui-results.py` compares actual GPU output byte-for-byte against the
software renderer in debug/O2/O3 and cross-generates Dyn objects for six targets.
Native Vulkan bridge qualification outside Linux remains separate platform work.
