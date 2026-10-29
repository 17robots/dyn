# FriBidi

Optional dynamic bindings for paragraph bidi resolution and wrapped-line
reordering. Open the native library through `std/dynlib`, pass its handle to
`load`, and keep the handle alive during API calls. No native library is linked
or installed by this package. The Linux module links libc for the dynamic
loader; older systems may additionally require libdl.

`resolve(arena, &api, text, base)` strictly validates UTF-8 and accepts one
single-line paragraph. Split LF, CR, FS, GS, RS, NEL, line separator and paragraph
separator before calling it. Base direction is `Auto`, `LeftToRight` or
`RightToLeft`. Empty paragraphs succeed without native calls; an empty or entirely
neutral paragraph can retain `Auto` as the resolved base.

The arena-owned `Paragraph` contains logical and visual scalar arrays, logical
UTF-8 byte `starts`/`ends`, both scalar-position maps, logical embedding levels,
native bidi types and resolved base direction. Maps include explicit bidi and
isolate controls, retaining a complete permutation of source scalar positions.
The convenience visual array can contain mirrored characters or Arabic
presentation forms; shape the original logical source with HarfBuzz, using the
levels and maps for positioning. Bidi resolution does not perform font fallback,
OpenType shaping or line breaking.

After selecting a logical scalar range for a wrapped line, call
`reorder(arena, &api, &paragraph, start, end)`. The returned map contains global
paragraph scalar indexes in visual order. Returned levels remain in logical order
for that range and include the line-specific trailing-whitespace reset. Paragraph
levels and maps remain unchanged. Flags zero leave mirroring, mark placement and
shaping to the renderer. Results copy all native data into the arena and remain
valid after the loader handle closes. Failed helpers rewind their own arena
allocations; malformed UTF-8, separators and invalid ranges fail before allocation.

The binding follows the upstream [public scalar typedefs](https://github.com/fribidi/fribidi/blob/master/lib/fribidi-types.h),
[bidi types](https://github.com/fribidi/fribidi/blob/master/lib/fribidi-bidi-types.h),
[paragraph convenience API](https://github.com/fribidi/fribidi/blob/master/lib/fribidi.h)
and [line-reordering contract](https://github.com/fribidi/fribidi/blob/master/lib/fribidi-bidi.h).
The ABI uses uint32 characters/types/directions, int32 indexes and signed 8-bit
levels, including the native return value. Line reordering implements the native
UAX #9 L1/L2/L3 behavior with flags zero.

`tests/text-bidi-vendor.py` compares complete scalar arrays, source byte ranges,
maps, levels, types and wrapped-line output against a separately compiled C
program using the installed FriBidi headers. Local qualification uses FriBidi
1.0.17: debug/O2/O3 execution and six other desktop target object builds. Object
builds do not establish native macOS or Windows runtime qualification.
