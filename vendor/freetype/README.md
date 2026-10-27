# FreeType

`load` resolves the selected FreeType 2 ABI from a caller-owned `std/dynlib`
handle. Keep that loader handle open until every native library/face and API table
is dead. C `long` follows the target ABI, including 32-bit Windows `long` on x64
and ARM64. Public face/glyph records are read only through a bounded prefix.

`open(font, api, bytes, face_index, pixel_height)` creates an owned native library
and memory face. Font bytes are borrowed until `close`; do not reset their arena
while the face is alive. `close` releases face before library and is idempotent.
Do not copy a live owning `Font`; keep it at a stable address until closed.
The wrapper reports native FT errors as `System` plus the numeric `error` value.

The raw table exposes glyph lookup/loading, rendering and kerning. After a render,
`bitmap(face)` returns borrowed normal gray8 coverage, bearings and 26.6 advances.
That coverage is invalidated by the next face load/render. Other pixel modes and
negative-pitch bitmaps return `Unsupported` rather than silently misreading them.

`Adapter` connects FreeType to `std/ui/software.Font`, usable by software, OpenGL
and Vulkan UI renderers. Keep the adapter at a stable address. `baseline` locates
the baseline relative to the pen; use zero with baseline-positioned glyph commands.
Set `glyph_ids` for HarfBuzz output and leave it false for Unicode lookup. Configure
`line_height` explicitly. Faces and their glyph slots require serialized access.

`tests/font-vendor-results.py` compares the bitmap, bearings and advances with an
independent C FreeType program, verifies HarfBuzz-shaped Arabic rendering through
the adapter, and checks Dyn object generation for six targets. Native ABI execution
outside Linux remains separate qualification work.
