#!/usr/bin/env python3
"""Bounded public Unicode result/arena contracts; independent fixed goldens."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve())


def literal(value):
    if isinstance(value, str):
        value = value.encode('utf-8')
    return '"' + ''.join('\\x%02x' % byte for byte in value) + '"'


SOURCE = '''use "std/unicode/text" text
use "std/mem" mem
use "std/bytes" bytes
use "std/errors" errors
fn require(ok: bool, message: []const u8) { if !ok { #panic(message) } }
fn converted(r: text.Converted, expected: []const u8) {
 require(r.ok && bytes.equal(r.value, expected), "conversion golden")
 require(r.kind == errors.Kind.None && r.error == 0 && r.offset == 0 && r.detail == text.ErrorKind.None, "success diagnostics")
}
fn convert(a: *mem.Arena, input: []const u8, mode: usize) text.Converted {
 if mode == 4 { return text.case_fold(a, input) }
 form := text.Form.NFD
 if mode == 1 { form = text.Form.NFC } else if mode == 2 { form = text.Form.NFKD } else if mode == 3 { form = text.Form.NFKC }
 return text.normalize(a, input, form)
}
fn good(input: []const u8, expected: []const u8, mode: usize) {
 backing: [8192]u8 = []
 mem.fill(backing[..], 99)
 a := mem.arena_from_buffer(backing[..])
 _ = mem.push_bytes_uninit(&a, 7)
 r := convert(&a, input, mode)
 converted(r, expected)
 require(mem.arena_mark(&a) == 7 + #len(expected), "exact retained allocation")
 for c in backing[..7] { require(c == 99, "prefix preserved") }
}
fn bad(input: []const u8, off: usize) {
 for mode in 0..5 {
  backing: [256]u8 = []
  mem.fill(backing[..], 99)
  a := mem.arena_from_buffer(backing[..])
  _ = mem.push_bytes_uninit(&a, 7)
  a.poison_on_rewind = true
  r := convert(&a, input, mode)
  require(!r.ok && #len(r.value) == 0 && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.offset == off && r.detail == text.ErrorKind.InvalidUtf8, "invalid diagnostics")
  require(mem.arena_mark(&a) == 7, "invalid rollback")
  for c in backing { require(c == 99, "validation wrote arena") }
  empty: [0]u8 = []
  full := mem.arena_from_buffer(empty[..])
  r = convert(&full, input, mode)
  require(!r.ok && r.offset == off && r.error == 0 && r.kind == errors.Kind.InvalidInput && r.detail == text.ErrorKind.InvalidUtf8 && #len(r.value) == 0 && mem.arena_mark(&full) == 0, "validate before allocation")
 }
}
fn overlap(start: usize, mode: usize) {
 backing: [1024]u8 = []
 snapshot: [1024]u8 = []
 mem.fill(backing[..], 99)
 _ = mem.copy(backing[start..], "ABCD")
 _ = mem.copy(snapshot[..], backing[..])
 a := mem.arena_from_buffer(backing[..])
 _ = mem.push_bytes_uninit(&a, 8)
 r := convert(&a, backing[start..start+4], mode)
 require(!r.ok && #len(r.value) == 0 && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.offset == 0 && r.detail == text.ErrorKind.Overlap, "overlap diagnostics")
 require(mem.arena_mark(&a) == 8 && bytes.equal(backing[..], snapshot[..]), "overlap preserved bytes and mark")
}
fn end(r: text.GraphemeResult) {
 require(!r.ok && #len(r.value) == 0 && r.kind == errors.Kind.None && r.error == 0 && r.offset == 0 && r.detail == text.ErrorKind.None, "ordinary EOF")
}
fn cluster(r: text.GraphemeResult, expected: []const u8) {
 require(r.ok && bytes.equal(r.value, expected) && r.kind == errors.Kind.None && r.error == 0 && r.offset == 0 && r.detail == text.ErrorKind.None, "grapheme value")
}
fn sticky(input: []const u8, off: usize, start: usize) {
 g := text.graphemes(input)
 g.offset = start
 for repeat in 0..3 {
  r := text.next_grapheme(&g)
  require(!r.ok && #len(r.value) == 0 && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.offset == off && r.detail == text.ErrorKind.InvalidUtf8, "sticky error diagnostics")
  require(g.offset == start && g.error == text.ErrorKind.InvalidUtf8, "sticky iterator state")
 }
}
fn main() {
 z := text.Converted{}
 require(!z.ok && #len(z.value) == 0 && z.kind == errors.Kind.None && z.error == 0 && z.offset == 0 && z.detail == text.ErrorKind.None, "zero Converted")
 end(text.GraphemeResult{})
 empty := text.graphemes("")
 end(text.next_grapheme(&empty))
 end(text.next_grapheme(&empty))
'''


def source():
    # Explicit goldens do not depend on the host Python Unicode database version.
    goldens = [
        ('Straße İ Σς', 'strasse i\u0307 σσ', 4), ('ﬃK', 'ffik', 4),
        ('é', 'e\u0301', 0), ('e\u0301', 'é', 1),
        ('각', '\u1100\u1161\u11a8', 0), ('\u1100\u1161\u11a8', '각', 1),
        ('a\u0315\u0300', 'a\u0300\u0315', 0),
        ('ﬃ①Ａ', 'ffi1A', 2), ('ﬃ①Ａ', 'ffi1A', 3),
        ('ﬃ①Ａ', 'ﬃ①Ａ', 0), ('ﬃ①Ａ', 'ﬃ①Ａ', 1),
    ] + [('', '', mode) for mode in range(5)]
    program = SOURCE
    for raw, expected, mode in goldens:
        program += f'good({literal(raw)}, {literal(expected)}, {mode})\n'
    malformed = [b'\x80', b'\xc0\xaf', b'\xc1\xbf', b'\xc2', b'\xe0\x80\x80',
                 b'\xed\xa0\x80', b'\xf0\x80\x80\x80', b'\xf4\x90\x80\x80',
                 b'\xf5\x80\x80\x80', b'\xff', b'\xe2\x82', b'\xe2A\xac']
    for prefix in [b'', b'abc', 'é🙂'.encode()]:
        for invalid in malformed:
            program += f'bad({literal(prefix + invalid + b"Z")}, {len(prefix)})\n'
    program += '''for mode in 0..4 {
 // capacity=24: work occupies [8,200), output [200,224).
 overlap(8, mode)
overlap(12, mode)
overlap(200, mode)
overlap(202, mode)
}
overlap(8, 4)
overlap(10, 4)
'''
    clusters = ['a\u0301', '\r\n', '🇺🇸', '👩\u200d💻', '각']
    program += f'g := text.graphemes({literal("".join(clusters))})\n'
    for value in clusters:
        program += f'cluster(text.next_grapheme(&g), {literal(value)})\n'
    program += 'end(text.next_grapheme(&g))\nend(text.next_grapheme(&g))\n'
    program += f'partial := text.graphemes({literal(b"ab" + bytes([255]))})\n'
    program += 'cluster(text.next_grapheme(&partial), "a")\n'
    program += '''for repeat in 0..3 {
 r := text.next_grapheme(&partial)
 require(!r.ok && #len(r.value) == 0 && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.offset == 2 && r.detail == text.ErrorKind.InvalidUtf8 && partial.offset == 1, "sticky after success")
}
'''
    for raw, off, start in [(b'\xff', 0, 0), (b'a\xff', 1, 0),
                            (b'ab\xff', 2, 1), ('é'.encode()+b'\xff', 2, 0)]:
        program += f'sticky({literal(raw)}, {off}, {start})\n'
    return program + '}\n', len(goldens), len(malformed) * 3


def build(work, mode):
    subprocess.run([DYN, 'build', str(work), '--' + mode, '--quiet', '--no-cache',
                    '--output', str(work / 'run')], cwd=ROOT, check=True, timeout=120)


def main():
    program, goldens, invalid = source()
    with tempfile.TemporaryDirectory(prefix='dyn-unicode-results-') as tmp:
        work = Path(tmp)
        for mode in ('debug', 'release'):
            (work / 'main.dyn').write_text(program)
            build(work, mode)
            subprocess.run([str(work / 'run')], check=True, capture_output=True, timeout=30)
            print(f'PASS Unicode {mode}: {goldens} goldens, {invalid} invalid UTF-8 cases × 5 operations; overlap, zero, grapheme EOF/sticky', flush=True)
            for operation in ['text.case_fold(&a, "ABCD")', 'text.normalize(&a, "ABCD", text.Form.NFD)']:
                (work / 'main.dyn').write_text('''use "std/unicode/text" text
use "std/mem" mem
fn main() {
 backing: [1]u8 = []
 a := mem.arena_from_buffer(backing[..])
 _ = OPERATION
}
'''.replace('OPERATION', operation))
                build(work, mode)
                result = subprocess.run([str(work / 'run')], capture_output=True, timeout=10)
                assert result.returncode != 0 and b'arena exhausted' in result.stderr, (mode, operation, result)
            print(f'PASS Unicode exhaustion panics {mode}: fold/normalize', flush=True)


if __name__ == '__main__':
    main()
