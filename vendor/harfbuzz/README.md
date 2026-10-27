# HarfBuzz

`load` resolves HarfBuzz from a caller-owned `std/dynlib` handle. Keep the library
loaded for the lifetime of native objects and API tables. The table includes blob,
face, font, buffer, feature, language/script and glyph-result operations.

`font_owned(api, bytes, face_index)` copies bytes into a native blob and returns an
owned OpenType font. Release it with `api.font_destroy`. Set `api.font_set_scale`
to the desired coordinate units; for 26.6 pixel positions at 32 pixels/em, use
`2048, 2048`. The default scale follows the font's design units.

`shape(arena, api, font, text, direction, features)` returns arena-owned glyph IDs,
UTF-8 byte clusters, advances and offsets. Direction zero guesses properties from
the run; explicit constants support LTR, RTL and vertical runs. Features use native
HarfBuzz tags and cluster ranges. Raw buffer results borrow native memory until
buffer mutation/destruction; the helper copies results before destroying it.

HarfBuzz shapes a directional run. Paragraph bidi resolution, font fallback,
wrapping and tag/language policy remain caller responsibilities. Send shaped IDs
to a FreeType UI adapter with `glyph_ids=true`; glyph IDs are not Unicode code
points. HarfBuzz's positive-up offsets must be converted for a UI's positive-down
y coordinates. Keep shaping and face access serialized when sharing mutable fonts.

`tests/font-vendor-results.py` compares complete Latin and Arabic glyph records
with an independent C HarfBuzz program and renders the Arabic result with FreeType.
