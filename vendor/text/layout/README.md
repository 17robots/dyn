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

## Visual selection geometry

`selection(arena, layout, start, end)` accepts a half-open logical UTF-8 byte
range and returns arena-owned `SelectionRect` values in visual line order.
Endpoints must be scalar boundaries. Any touched canonical shaped cluster is
selected in full, including a ligature or base-plus-mark grapheme. The function
does not change source bytes, glyph placements or line records. Empty ranges
allocate nothing. Invalid ranges or malformed layout slices fail before
allocation. Selection scans source, lines and glyphs linearly.

Each rectangle includes line index, pixel coordinates, line height and the
selected source `start/end` hull. That hull is metadata, not a promise that a
bidi transition forms a contiguous logical run. Draw the geometry rather than
reconstructing a band from the hull's source endpoints. Adjacent selected visual
cells merge on the same line; unselected positive-width cells prevent merging.
A logical range can therefore yield multiple separated rectangles on one line.

Tabs contribute their positive advance even though their placements are hidden.
Zero-width format controls and paragraph separators have no selection cell.
The application supplies newline extension, empty-line highlighting and clip
policy. Rectangles follow logical advance cells rather than glyph ink offsets.
Results own copied geometry and remain valid independently of later layout
mutation, until the destination arena is rewound or released.

`tests/text-shaped-selection.py` derives selection unions from the independent
C HarfBuzz/FriBidi glyph oracle for all scalar-boundary intervals in mixed-script
fixtures. It also covers discontiguous visual regions, partial ligatures and
marks, tabs/newlines, caller-arena ownership, invalid ranges/slices and a
20,000-glyph line in debug/O2/O3 plus six desktop object targets.
