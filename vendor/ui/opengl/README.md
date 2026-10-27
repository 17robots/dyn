# OpenGL UI renderer

Load `vendor/opengl` from a current GL 3.3+ context, then `open` a `Renderer`, call
`render` after `ui.end`, and `close` before destroying the context. Rectangles,
text and positioned glyphs use GPU quads, per-command scissor clipping and R8
coverage textures. The font callback is the same `std/ui/software.Font` contract;
coverage is uploaded before the next callback, including atlas views whose final
row omits padding. There is no persistent glyph atlas/cache in this adapter.

The target must be opaque. Conventional GL alpha blending preserves the expected
RGB result over an opaque destination; arbitrary straight-alpha transparent
destinations require the software or Vulkan renderer. Rendering owns GL viewport,
program, vertex bindings, texture unit zero, unpack state, blend and clip state,
and configures color writes and filled polygons. It disables depth/cull/stencil,
framebuffer-sRGB, logic-op, rasterizer discard, dithering, multisample coverage
controls, polygon smoothing and user clip planes. Reset state needed by subsequent GL work.
The caller owns framebuffer selection, clearing, presentation, and synchronization
with other GL users. Do not invoke rendering inside active transform feedback or
conditional rendering. Open/render drain GL error flags and return `System` for
preexisting or newly observed GL errors; errors may leave earlier draws visible.
Only visible glyph coverage is uploaded, so a narrow clip can render a glyph
larger than the device texture limit. A visible crop exceeding that limit returns
`Capacity`.

`tests/native-ui-results.py` compares every framebuffer component with the software
renderer (one-unit fixed-point blend tolerance) using actual native contexts.
