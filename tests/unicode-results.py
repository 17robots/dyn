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
 backing: [8192+mem.ArenaBufferOverhead]u8 = []
 mem.fill(backing[..], 99)
 a := mem.arena_from_buffer(backing[..])
 prefix := mem.push_bytes_uninit(a, 7)
 r := convert(a, input, mode)
 converted(r, expected)
 require(mem.arena_mark(a) == mem.arena_start(a) + 7 + #len(expected), "exact retained allocation")
 for c in prefix { require(c == 99, "prefix preserved") }
}
fn chained(input: []const u8, expected: []const u8, mode: usize, block: usize, prior: bool) {
 a := mem.arena_create_bounded(block, 1024 * 1024)
 defer mem.arena_release(a)
 prefix := mem.push_bytes_uninit(a, 3)
 mem.fill(prefix, 91)
 guard: []u8
 if prior {
  guard = mem.push_bytes_uninit(a, 257)
  mem.fill(guard, 73)
  require(mem.arena_snapshot(a).blocks > 1, "forced prior chain")
 }
 owned_input := mem.push_bytes_uninit(a, #len(input))
 _ = mem.copy(owned_input, input)
 mark := mem.arena_mark(a)
 used := mem.arena_used(a)
 r := convert(a, owned_input, mode)
 converted(r, expected)
 require(mem.arena_mark(a) == mark + #len(expected), "chained exact retained mark")
 require(mem.arena_used(a) == used + #len(expected), "chained scratch reclaimed")
 require(bytes.equal(owned_input, input), "live input preserved across chain")
 for value in prefix { require(value == 91, "chained prefix canary") }
 for value in guard { require(value == 73, "earlier block canary") }
 mem.arena_rewind(a, mark)
 require(mem.arena_mark(a) == mark && bytes.equal(owned_input, input), "chained output rollback")
 for value in prefix { require(value == 91, "prefix after rollback") }
 for value in guard { require(value == 73, "prior block after rollback") }
}
fn bad(input: []const u8, off: usize) {
 for mode in 0..5 {
  backing: [256+mem.ArenaBufferOverhead]u8 = []
  mem.fill(backing[..], 99)
  a := mem.arena_from_buffer(backing[..])
  prefix := mem.push_bytes_uninit(a, 7)
  a.poison_on_rewind = true
  snapshot: [256+mem.ArenaBufferOverhead]u8
  _ = mem.copy(snapshot[..], backing[..])
  r := convert(a, input, mode)
  require(!r.ok && #len(r.value) == 0 && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.offset == off && r.detail == text.ErrorKind.InvalidUtf8, "invalid diagnostics")
  require(mem.arena_mark(a) == mem.arena_start(a) + 7, "invalid rollback")
  require(bytes.equal(backing[..], snapshot[..]), "validation wrote arena")
  empty: [mem.ArenaBufferOverhead]u8 = []
  pad := (16-(#cast(usize,&empty[0])&15))&15
  full := mem.arena_from_buffer(empty[pad..pad+mem.ArenaHeader])
  r = convert(full, input, mode)
  require(!r.ok && r.offset == off && r.error == 0 && r.kind == errors.Kind.InvalidInput && r.detail == text.ErrorKind.InvalidUtf8 && #len(r.value) == 0 && mem.arena_mark(full) == mem.arena_start(full), "validate before allocation")
 }
}
fn overlap(start: usize, mode: usize) {
 backing: [1024+mem.ArenaBufferOverhead]u8 = []
 snapshot: [1024+mem.ArenaBufferOverhead]u8 = []
 mem.fill(backing[..], 99)
 a := mem.arena_from_buffer(backing[..])
 _ = mem.push_bytes_uninit(a, 8)
 at := mem.arena_start(a) + start
 _ = mem.copy(a.data[at..], "ABCD")
 payload := a.data[mem.ArenaHeader..]
 _ = mem.copy(snapshot[..], payload)
 r := convert(a, a.data[at..at+4], mode)
 require(!r.ok && #len(r.value) == 0 && r.kind == errors.Kind.InvalidInput && r.error == 0 && r.offset == 0 && r.detail == text.ErrorKind.Overlap, "overlap diagnostics")
 require(mem.arena_mark(a) == mem.arena_start(a) + 8 && bytes.equal(payload, snapshot[..#len(payload)]), "overlap preserved bytes and mark")
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
        for block in (160, 176, 256):
            for prior in (False, True):
                program += f'chained({literal(raw)}, {literal(expected)}, {mode}, {block}, {str(prior).lower()})\n'
    for raw, expected, mode in [('é' * 160, 'e\u0301' * 160, 0),
                                 ('a\u0315\u0300' * 80, 'a\u0300\u0315' * 80, 0),
                                 ('ﬃ①Ａ' * 80, 'ffi1A' * 80, 2),
                                 ('Straße' * 100, 'strasse' * 100, 4)]:
        for block in (160, 176, 256):
            for prior in (False, True):
                program += f'chained({literal(raw)}, {literal(expected)}, {mode}, {block}, {str(prior).lower()})\n'
    malformed = [b'\x80', b'\xc0\xaf', b'\xc1\xbf', b'\xc2', b'\xe0\x80\x80',
                 b'\xed\xa0\x80', b'\xf0\x80\x80\x80', b'\xf4\x90\x80\x80',
                 b'\xf5\x80\x80\x80', b'\xff', b'\xe2\x82', b'\xe2A\xac']
    for prefix in [b'', b'abc', 'é🙂'.encode()]:
        for invalid in malformed:
            program += f'bad({literal(prefix + invalid + b"Z")}, {len(prefix)})\n'
    program += '''for mode in 0..4 {
 // For four input bytes, capacity=24: relative to the payload start,
 // work occupies [8,200), output [200,224); trailing alignment slack follows.
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


def build(work, mode, tree=False):
    env = dict(os.environ, DYN_SDK=str(ROOT))
    if tree:
        env["DYN_NO_SSA"] = "1"
    else:
        env.pop("DYN_NO_SSA", None)
    subprocess.run([DYN, 'build', str(work), '--' + mode, '--quiet', '--no-cache',
                    '--output', str(work / 'run')], cwd=ROOT, env=env, check=True, timeout=120)


def main():
    program, goldens, invalid = source()
    with tempfile.TemporaryDirectory(prefix='dyn-unicode-results-') as tmp:
        work = Path(tmp)
        for mode in ('debug', 'release'):
            for tree in (False, True):
                (work / 'main.dyn').write_text(program)
                build(work, mode, tree)
                subprocess.run([str(work / 'run')], check=True, capture_output=True, timeout=30)
                print(f'PASS Unicode {mode} {"tree" if tree else "SSA"}: {goldens} goldens, {invalid} invalid UTF-8 cases × 5 operations; 120 chained conversions, overlap, zero, grapheme EOF/sticky', flush=True)
                for operation in ['text.case_fold(a, "ABCD")', 'text.normalize(a, "ABCD", text.Form.NFD)']:
                    (work / 'main.dyn').write_text('''use "std/unicode/text" text
    use "std/mem" mem
    fn main() {
     backing: [1+mem.ArenaBufferOverhead]u8 = []
     pad := (16-(#cast(usize,&backing[0])&15))&15
     a := mem.arena_from_buffer(backing[pad..pad+mem.ArenaHeader+1])
     _ = OPERATION
    }
    '''.replace('OPERATION', operation))
                    build(work, mode, tree)
                    result = subprocess.run([str(work / 'run')], capture_output=True, timeout=10)
                    assert result.returncode == 101 and b'arena exhausted' in result.stderr, (mode, operation, result)
                print(f'PASS Unicode exhaustion panics {mode} {"tree" if tree else "SSA"}: fold/normalize', flush=True)

if __name__ == '__main__':
    main()
