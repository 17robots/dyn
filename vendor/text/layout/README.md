# Directional shaped text layout

`vendor/text/layout` combines caller-owned HarfBuzz and FriBidi API tables with
Unicode grapheme and line-break segmentation. It does not load libraries or own
native fonts. Keep both loader handles open while building layouts; keep each
selected face and its raster owner alive while using the resulting glyphs.

`Font.select(data, grapheme)` receives a complete extended grapheme and returns
`Face{font, data}`. `font` is a HarfBuzz font scaled to 26.6 pixel units. `data` is
an opaque raster owner copied into the output `Glyph.font` field. Font selection
must stay stable during one build. `line_height` is a positive integer pixel
height; `space_advance` is a positive finite pixel advance used for tab stops.

`build(arena, source, font, hb_api, bidi_api, options)` owns a source byte copy,
visual glyph placements and line records in the caller arena. It preserves the
original UTF-8 bytes without normalization. Invalid input or a shaping error
rewinds the arena to its original mark. `Options.base` accepts FriBidi Auto, LTR
or RTL; width zero disables wrapping. CRLF and Unicode paragraph separators
create distinct lines, including trailing empty lines.

Each paragraph resolves native bidi embedding levels. Each accepted line applies
FriBidi's line-specific L1/L2 reordering and shapes directional script/font runs.
Runs retain the full accepted line as HarfBuzz context, including across fallback
font boundaries; beginning/end flags apply only at actual line edges.
HarfBuzz glyph IDs, advances and offsets are retained in pixel units; positive-up
native y offsets become positive-down `y_offset`. Add `x_offset/y_offset` to the
visual pen `x/y` when drawing. Hidden placements preserve tab/format ranges and
must not be rasterized. Tabs advance to the next `space_advance * tab_columns`
stop. A soft hyphen becomes a visible hyphen only at an accepted wrap boundary.

Wrapping operates on shaped clusters and UAX #14 opportunities, then reshapes
and measures each accepted line. An indivisible overwide cluster stays intact.
HarfBuzz can expose sub-grapheme missing-glyph clusters; output ranges merge
those into extended graphemes so wrapping and hit queries never split a mark.
Common/inherited scripts inherit a neighboring strong script. This itemizer does
not implement the full Unicode ScriptExtensions/paired-punctuation policy.

`cluster_at(layout, byte_offset)` returns a logical source cluster rectangle.
EOF and separator positions return zero-width logical carets; their visual edge
follows the ending run direction, including mixed-direction lines. `at_point`
returns a visual cluster or a boundary caret outside the first/last cluster.
Both return `Hit.ok=false` for invalid queries. They expose one caret affinity;
applications needing distinct upstream/downstream carets at a bidi transition
must retain that additional selection policy themselves.

`tests/text-shaped-vendor.py` compares full glyph records with an independent C
HarfBuzz/FriBidi oracle for Latin ligatures, Arabic, Hebrew, mixed text, marks,
controls and tabs. A separate Arabic fixture alternates two native fonts within
one joining word and compares the contextual forms. It checks wrapping, source ranges, missing-glyph graphemes,
soft hyphens, hit queries, atomic errors and a 20,000-glyph unwrapped line. Host
execution covers debug/O2/O3; six desktop targets compile objects separately.
