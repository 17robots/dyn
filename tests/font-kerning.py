#!/usr/bin/env python3
"""Legacy OpenType kern: independent synthetic pair/flag and parser-error cases."""
import os
from pathlib import Path
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())


def u16(value):
    return struct.pack('>H', value)


def i16(value):
    return struct.pack('>h', value)


def u32(value):
    return struct.pack('>I', value)


def subtable(pairs=(), coverage=1, version=0):
    body = u16(len(pairs)) + b'\0' * 6
    body += b''.join(u16(left) + u16(right) + i16(value) for left, right, value in pairs)
    return u16(version) + u16(6 + len(body)) + u16(coverage) + body


def kern(subtables):
    return u16(0) + u16(len(subtables)) + b''.join(subtables)


def fixture(kerning=None):
    """A small face with five empty glyphs and a valid Unicode cmap 12."""
    head = bytearray(54)
    head[12:16] = u32(0x5f0f3cf5)
    head[18:20] = u16(1000)
    hhea = bytearray(36)
    hhea[4:10] = i16(1000) + i16(-200) + i16(0)
    hhea[34:36] = u16(1)
    cmap = u16(0) + u16(1) + u16(3) + u16(10) + u32(12)
    cmap += u16(12) + u16(0) + u32(28) + u32(0) + u32(1)
    cmap += u32(65) + u32(68) + u32(1)
    tables = {
        b'head': bytes(head), b'hhea': bytes(hhea),
        b'maxp': u32(0x10000) + u16(5),
        b'hmtx': u16(500) + i16(0) + i16(0) * 4,
        b'loca': u16(0) * 6, b'glyf': b'', b'cmap': cmap,
    }
    if kerning is not None:
        tables[b'kern'] = kerning
    offset = 12 + 16 * len(tables)
    directory = b''
    body = b''
    locations = {}
    records = {}
    for tag, data in tables.items():
        records[tag] = 12 + len(directory)
        locations[tag] = offset
        directory += tag + u32(0) + u32(offset) + u32(len(data))
        body += data
        offset += len(data)
    return bytearray(u32(0x10000) + u16(len(tables)) + b'\0' * 6 + directory + body), locations, records


# Each error offset is relative to the kern table. Directories are tested below.
summed = kern([
    subtable([(1, 2, -100), (1, 3, 20)]),
    subtable([(1, 2, -25)]),
    subtable([(1, 2, -80)], coverage=9),
    subtable([(1, 2, 10)]),
    # This override lacks (1,2), so it must not erase its accumulated value.
    subtable([(2, 3, -99)], coverage=9),
])
ignored = kern([
    subtable([(1, 2, -75)]),
    # Six-byte headers deliberately omit format-0 data for unsupported semantics.
    u16(0) + u16(6) + u16(3),       # minimum
    u16(0) + u16(6) + u16(5),       # cross-stream
    u16(0) + u16(6) + u16(0),       # vertical
    u16(0) + u16(6) + u16(0x201),   # format 2
    u16(1) + u16(6) + u16(1),       # unknown subtable version
    u16(0) + u16(6) + u16(0x11),    # reserved coverage bit
])
cases = [
    ('absent', None, True, (0.0, 0.0, 0.0), None, False),
    ('empty', kern([]), True, (0.0, 0.0, 0.0), None, True),
    ('empty_pairs', kern([subtable()]), True, (0.0, 0.0, 0.0), None, True),
    ('sum_override', summed, True, (-1.12, 0.32, -1.584), None, True),
    ('unsupported_subtables', ignored, True, (-1.2, 0.0, 0.0), None, True),
    ('unknown_table_version', u16(1), True, (0.0, 0.0, 0.0), None, False),
    ('signed_min', kern([subtable([(1, 2, -32768)])]), True, (-524.288, 0.0, 0.0), None, True),
    ('signed_max', kern([subtable([(1, 2, 32767)])]), True, (524.272, 0.0, 0.0), None, True),
    ('empty_table', b'', False, (), 0, False),
    ('short_version', b'\0', False, (), 0, False),
    ('short_table_header', u16(0), False, (), 0, False),
    ('short_subtable_header', u16(0) + u16(1) + b'\0' * 5, False, (), 4, False),
    ('short_subtable_length', kern([u16(0) + u16(5) + u16(1)]), False, (), 6, False),
    ('subtable_outside_table', kern([u16(0) + u16(20) + u16(1)]), False, (), 6, False),
    ('short_format0_header', kern([u16(0) + u16(6) + u16(1)]), False, (), 6, False),
    ('duplicate_pair', kern([subtable([(1, 2, -100), (1, 2, -200)])]), False, (), 24, False),
    ('unsorted_pairs', kern([subtable([(2, 1, 1), (1, 2, 2)])]), False, (), 24, False),
    ('invalid_glyph', kern([subtable([(1, 9, 1)])]), False, (), 18, False),
    ('missing_second_subtable', u16(0) + u16(2) + subtable([(1, 2, 1)]), False, (), 24, False),
]
# Pair count 2 with only one pair record must fail at the count, not bounds-trap.
bad_count = bytearray(kern([subtable([(1, 2, 1)])]))
bad_count[10:12] = u16(2)
cases.append(('pair_count_overrun', bytes(bad_count), False, (), 10, False))

with tempfile.TemporaryDirectory(prefix='dyn-font-kerning-') as directory:
    work = Path(directory)
    for name, table, ok, expected, relative_offset, borrowed in cases:
        data, locations, _ = fixture(table)
        source = ('use "std/font" font\nuse "std/math" math\nuse "std/errors" errors\n'
                  'data: []const u8 = "' + ''.join('\\x%02x' % byte for byte in data) + '"\n'
                  'fn main() {\n  face := font.open(data)\n')
        source += f'  if face.ok != {str(ok).lower()} {{ #panic("{name}: status") }}\n'
        if ok:
            source += f'  if face.kind != errors.Kind.None || face.error != 0 || face.offset != 0 {{ #panic("{name}: metadata") }}\n'
            source += f'  if font.glyph_index(&face.value, 65) != 1 {{ #panic("{name}: cmap compatibility") }}\n'
            for left, right, want in ((1, 2, expected[0]), (1, 3, expected[1]), (2, 3, expected[2])):
                source += f'  if math.abs(font.kerning(&face.value, {left}, {right}, 16) - {want}) > 0.000001 {{ #panic("{name}: pair {left} {right}") }}\n'
            if borrowed:
                source += f'  if #cast(usize, &face.value.kern[0]) != #cast(usize, &data[{locations[b"kern"]}]) {{ #panic("{name}: borrowed table") }}\n'
            else:
                source += f'  if #len(face.value.kern) != 0 {{ #panic("{name}: ignored table") }}\n'
            source += '  if font.kerning(&face.value, 4, 4, 16) != 0.0 || font.kerning(&face.value, 99, 1, 16) != 0.0 || font.kerning(&face.value, 1, 99, 16) != 0.0 || font.kerning(&face.value, 1, 2, 0) != 0.0 || font.kerning(&face.value, 1, 2, 257) != 0.0 { #panic("miss or invalid query") }\n'
        else:
            offset = locations[b'kern'] + relative_offset
            source += f'  if face.kind != errors.Kind.InvalidInput || face.error != 0 || face.offset != {offset} {{ #panic("{name}: error metadata") }}\n'
            source += f'  if #len(face.value.data) != 0 || #len(face.value.kern) != 0 {{ #panic("{name}: failure value") }}\n'
        source += '}\n'
        (work / 'main.dyn').write_text(source)
        for mode in ('--debug', '--release'):
            output = work / 'program'
            subprocess.run([DYN, 'build', str(work), mode, '--quiet', '--no-cache', '--output', str(output)], check=True, timeout=300)
            subprocess.run([str(output)], check=True, timeout=30)
    # The optional table's directory span must also be checked before parsing.
    for field in ('offset', 'length'):
        data, _, records = fixture(summed)
        at = records[b'kern']
        field_at = at + (8 if field == 'offset' else 12)
        data[field_at:field_at + 4] = u32(len(data) + 100)
        (work / 'main.dyn').write_text('use "std/font" font\nuse "std/errors" errors\ndata: []const u8 = "' + ''.join('\\x%02x' % byte for byte in data) + '"\nfn main() {\n face := font.open(data)\n if face.ok || face.kind != errors.Kind.InvalidInput || face.error != 0 || face.offset != ' + str(at + 8) + ' { #panic("kern directory bounds") }\n}\n')
        for mode in ('--debug', '--release'):
            output = work / 'program'
            subprocess.run([DYN, 'build', str(work), mode, '--quiet', '--no-cache', '--output', str(output)], check=True, timeout=300)
            subprocess.run([str(output)], check=True, timeout=30)
print(f'PASS font kerning: {len(cases) + 2} synthetic cases, no-kern compatibility, sum/override, flags, borrowed storage and precise parser errors (debug/release)')
