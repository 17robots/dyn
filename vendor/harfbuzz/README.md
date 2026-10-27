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

`shape_run` accepts `Options` with explicit direction, script, language, cluster
level and buffer flags. Empty properties are guessed as in `shape`. Cluster
levels 0..2 cover monotone graphemes, monotone characters and ungrouped
characters. Flags `BeginningOfText`/`EndOfText` identify true text boundaries;
do not set them on fragments lacking their surrounding context. Language tags
use explicit byte lengths and reject embedded NUL. The table also exposes
Unicode script lookup and script horizontal direction for run itemization.
See [HarfBuzz buffer properties](https://harfbuzz.github.io/setting-buffer-properties.html)
and [clusters](https://harfbuzz.github.io/working-with-harfbuzz-clusters.html).

For paragraph bidi, script runs, wrapping and source cluster queries, use
[`vendor/text/layout`](../text/layout/README.md) with a FriBidi API table.

`Options.item_offset` and `item_length` select a UTF-8 byte range while retaining
the full `text` as shaping context. Length -1 means the remaining bytes. Bounds
are checked before allocation. Returned clusters remain offsets into the full
text, so normalize them only when exposing a run-relative API. This permits
Arabic joining across font boundaries without marking every font run as a
separate paragraph.
