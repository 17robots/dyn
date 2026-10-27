#!/usr/bin/env python3
"""Font discovery: owned metadata, strict names, defaults, traversal and coverage."""
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
# Reuse the small, independently assembled TrueType fixture without running
# the rasterizer test harness.
fixture_namespace = {'__file__': str(ROOT / 'tests/font-results.py')}
exec((ROOT / 'tests/font-results.py').read_text().split('SOURCE =')[0], fixture_namespace)
base, _ = fixture_namespace['fixture']()
u16 = lambda n: struct.pack('>H', n)
u32 = lambda n: struct.pack('>I', n)

def face(family, style='Regular', weight=400, italic=False, mono=False):
    count = struct.unpack_from('>H', base, 4)[0]
    tables = {}
    for i in range(count):
        tag, _, at, length = struct.unpack_from('>4sIII', base, 12 + i * 16)
        tables[tag] = base[at:at + length]
    names = [(16, family), (17, style)]
    records, strings = b'', b''
    for name_id, value in names:
        raw = value if isinstance(value, bytes) else value.encode('utf-16-be')
        records += struct.pack('>6H', 3, 1, 0x409, name_id, len(raw), len(strings))
        strings += raw
    tables[b'name'] = u16(0) + u16(2) + u16(30) + records + strings
    os2 = bytearray(64)
    os2[4:6] = u16(weight)
    os2[62:64] = u16(int(italic))
    tables[b'OS/2'] = os2
    tables[b'post'] = bytes(12) + u32(int(mono))
    at = 12 + 16 * len(tables)
    directory, body = b'', b''
    for tag, data in tables.items():
        directory += tag + u32(0) + u32(at) + u32(len(data))
        body += data
        at += len(data)
    return u32(65536) + u16(len(tables)) + bytes(6) + directory + body

SOURCE = r'''use "std/font/system" system
use "std/mem" mem
use "std/bytes" bytes
fn check(ok: bool, label: []const u8) { if !ok { #panic(label) } }
fn main() {
  arena := mem.Arena{}
  defer { mem.arena_release(&arena) }
  regular := system.describe(&arena, "regular.ttf", regular_data[..])
  check(bytes.equal(regular.family, "Test 😀") && bytes.equal(regular.style, "Regular"), "check 39")
  check(regular.weight == 400 && regular.monospace && !regular.italic, "check 40")
  bold := system.describe(&arena, "bold.ttf", bold_data[..])
  check(bold.weight == 700 && bold.italic, "check 42")
  entries: [2]system.Entry = [regular, bold]
  check(system.find(entries[..], "TEST 😀", 700, true) == &entries[1], "check 44")
  check(#len(system.find(entries[..], "missing", 400, false).path) == 0, "check 45")
  check(system.monospace(entries[..]) == &entries[0], "check 46")
  check(#len(system.sans(entries[..]).path) == 0, "check 47")
  preferred: [2][]const u8 = ["missing", "Test 😀"]
  check(system.first_of(entries[..], preferred[..], 400, false) == &entries[0], "check 49")
  before := mem.arena_mark(&arena)
  for n in 0..#len(regular_data) {
    rejected := system.describe(&arena, "truncated.ttf", regular_data[..n])
    check(#len(rejected.family) == 0 && mem.arena_mark(&arena) == before, "check 53")
  }
  rejected := system.describe(&arena, "invalid.ttf", invalid_data[..])
  check(#len(rejected.family) == 0 && mem.arena_mark(&arena) == before, "check 56")
  // Strings remain valid after the caller mutates the original file bytes.
  for i in 0..#len(regular_data) { regular_data[i] = 0 }
  check(bytes.equal(regular.family, "Test 😀"), "check 59")
}'''
with tempfile.TemporaryDirectory(prefix='dyn-font-system-') as directory:
    work = Path(directory)
    regular = face('Test 😀', mono=True)
    bold = face('Test 😀', 'Bold Italic', 700, True, True)
    invalid = face(b'\xd8\x00\x00A')
    declarations = ''.join(f'{name}: [{len(data)}]u8 = [{",".join(map(str, data))}]\n'
                           for name, data in [('regular_data', regular), ('bold_data', bold), ('invalid_data', invalid)])
    (work / 'main.dyn').write_text(declarations + SOURCE)
    for mode in ('--debug', '--release'):
        output = work / 'test'
        subprocess.run([DYN, 'build', str(work), mode, '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], check=True, timeout=90)
    for target in ('aarch64-linux', 'riscv64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows'):
        output = work / target
        subprocess.run([DYN, 'build', str(work), '--release', '--target', target, '--quiet', '--output', str(output)], check=True, timeout=300)
        emulator = {'aarch64-linux': 'qemu-aarch64', 'riscv64-linux': 'qemu-riscv64', 'x86_64-windows': 'wine'}.get(target)
        if emulator and shutil.which(emulator):
            subprocess.run([emulator, str(output)], check=True, timeout=120)
    fonts = work / 'fonts'
    (fonts / 'nested').mkdir(parents=True)
    (fonts / 'regular.TTF').write_bytes(regular)
    (fonts / 'nested/bold.ttf').write_bytes(bold)
    (fonts / 'invalid.ttf').write_bytes(invalid)
    (fonts / 'ignored.txt').write_bytes(regular)
    path_literal = str(fonts).replace('\\', '\\\\').replace('"', '\\"')
    (work / 'main.dyn').write_text(r'''use "std/font/system" system
use "std/mem" mem
fn check(ok: bool) { if !ok { #panic("font scan contract") } }
fn main() {
  arena := mem.Arena{}
  defer { mem.arena_release(&arena) }
  directories: [2][]const u8 = ["MISSING_DIRECTORY", "FONT_DIRECTORY"]
  check(#len(system.scan_directories(&arena, directories[..], 0)) == 0)
  entries := system.scan_directories(&arena, directories[..], 20)
  check(#len(entries) == 2)
  check(#len(system.scan_directories(&arena, directories[..], 1)) == 1)
  check(#len(system.covering(entries, 65, true).path) != 0)
  check(#len(system.covering(entries, 0x10ffff, false).path) == 0)
  _ = system.scan(&arena, 4)
}
'''.replace('FONT_DIRECTORY', path_literal))
    for mode in ('--debug', '--release'):
        output = work / 'scan'
        subprocess.run([DYN, 'build', str(work), mode, '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], check=True, timeout=90)
print('PASS system fonts: metadata ownership, UTF-16, malformed names, selection, recursive scan, caps, glyph fallback and desktop cross-builds')
