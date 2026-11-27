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


SOURCE = '''use text "std/unicode/text"
use mem "std/mem"
use bytes "std/bytes"
use parse "std/parse"
fn require(ok: bool, message: []const u8) { if !ok { #panic(message) } }
enum Kind { Ok, InvalidInput, Capacity, Unsupported }
struct Failure { kind: Kind, offset: usize }
fn failure_of(err: parse.ParseErr) Failure {
 case err {
  .Invalid(at) => { return Failure{ kind: Kind.InvalidInput, offset: at } }
  .TooLarge(at) => { return Failure{ kind: Kind.Capacity, offset: at } }
  .Unsupported(at) => { return Failure{ kind: Kind.Unsupported, offset: at } }
 }
}
struct Converted { value: []u8, offset: usize, failure: Failure }
struct Grapheme { value: []const u8, found: bool, offset: usize, failure: Failure }
fn next_grapheme(g: *text.Graphemes) Grapheme {
 r := text.next_grapheme(g) catch err {
  failure := failure_of(err)
  return Grapheme{ found: !g.ended, offset: failure.offset, failure: failure }
 }
 return Grapheme{ value: r, found: !g.ended }
}
fn converted(r: Converted, expected: []const u8) {
 require(r.failure.kind == Kind.Ok && bytes.equal(r.value, expected), "conversion golden")
 require(r.failure.kind == Kind.Ok && r.offset == 0, "success diagnostics")
}
fn failed(err: parse.ParseErr) Converted {
 failure := failure_of(err)
 return Converted{ offset: failure.offset, failure: failure }
}
fn convert(a: *mem.Arena, input: []const u8, mode: usize) Converted {
 if mode == 4 {
  folded := text.case_fold(a, input) catch err { return failed(err) }
  return Converted{ value: folded }
 }
 form := text.Form.NFD
 if mode == 1 { form = text.Form.NFC } else if mode == 2 { form = text.Form.NFKD } else if mode == 3 { form = text.Form.NFKC }
 value := text.normalize(a, input, form) catch err { return failed(err) }
 return Converted{ value: value }
}
fn good(input: []const u8, expected: []const u8, mode: usize) {
 backing: [8192+mem.ArenaBufferOverhead]u8
 mem.fill(backing[..], 99)
 a := mem.arena_from_buffer(backing[..])
 prefix := mem.push_bytes(a, 7)
 r := convert(a, input, mode)
 converted(r, expected)
 require(mem.arena_mark(a) == mem.ArenaHeader + 7 + expected.len, "exact retained allocation")
 for c in prefix { require(c == 99, "prefix preserved") }
}
fn chained(input: []const u8, expected: []const u8, mode: usize, block: usize, prior: bool) {
 source := mem.pages(1024 * 1024)
 source.block_size = block
 a := mem.arena_from_source(source)
 defer mem.arena_release(a)
 prefix := mem.push_bytes(a, 3)
 mem.fill(prefix, 91)
 guard: []u8
 if prior {
  guard = mem.push_bytes(a, 257)
  mem.fill(guard, 73)
  require(a.current != a, "forced prior chain")
 }
 owned_input := mem.push_bytes(a, input.len)
 _ = mem.copy(owned_input, input)
 mark := mem.arena_mark(a)
 used := mem.arena_used(a)
 r := convert(a, owned_input, mode)
 converted(r, expected)
 require(mem.arena_mark(a) == mark + expected.len, "chained exact retained mark")
 require(mem.arena_used(a) == used + expected.len, "chained scratch reclaimed")
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
  backing: [256+mem.ArenaBufferOverhead]u8
  mem.fill(backing[..], 99)
  a := mem.arena_from_buffer(backing[..])
  prefix := mem.push_bytes(a, 7)
  a.poison_on_rewind = true
  snapshot: [256+mem.ArenaBufferOverhead]u8
  _ = mem.copy(snapshot[..], backing[..])
  r := convert(a, input, mode)
  require(r.failure.kind != Kind.Ok && r.value.len == 0 && r.failure.kind == Kind.InvalidInput && r.offset == off, "invalid diagnostics")
  require(mem.arena_mark(a) == mem.ArenaHeader + 7, "invalid rollback")
  require(bytes.equal(backing[..], snapshot[..]), "validation wrote arena")
  empty: [mem.ArenaBufferOverhead]u8
  pad := (16-(#cast(usize,&empty[0])&15))&15
  full := mem.arena_from_buffer(empty[pad..pad+mem.ArenaHeader])
  r = convert(full, input, mode)
  require(r.failure.kind != Kind.Ok && r.offset == off && r.failure.kind == Kind.InvalidInput && r.value.len == 0 && mem.arena_mark(full) == mem.ArenaHeader, "validate before allocation")
 }
}
fn overlap(start: usize, mode: usize) {
 backing: [1024+mem.ArenaBufferOverhead]u8
 snapshot: [1024+mem.ArenaBufferOverhead]u8
 mem.fill(backing[..], 99)
 a := mem.arena_from_buffer(backing[..])
 _ = mem.push_bytes(a, 8)
 at := mem.ArenaHeader + start
 _ = mem.copy(a.data[at..], "ABCD")
 payload := a.data[mem.ArenaHeader..]
 _ = mem.copy(snapshot[..], payload)
 r := convert(a, a.data[at..at+4], mode)
 require(r.failure.kind != Kind.Ok && r.value.len == 0 && r.failure.kind == Kind.InvalidInput && r.offset == 0, "overlap diagnostics")
 require(mem.arena_mark(a) == mem.ArenaHeader + 8 && bytes.equal(payload, snapshot[..payload.len]), "overlap preserved bytes and mark")
}
fn end(r: Grapheme) {
 require(!r.found && r.value.len == 0 && r.failure.kind == Kind.Ok && r.offset == 0, "ordinary EOF")
}
fn cluster(r: Grapheme, expected: []const u8) {
 require(r.found && bytes.equal(r.value, expected) && r.failure.kind == Kind.Ok && r.offset == 0, "grapheme value")
}
fn sticky(input: []const u8, off: usize, start: usize) {
 g := text.graphemes(input)
 g.offset = start
 for repeat in 0..3 {
  r := next_grapheme(&g)
  require(r.failure.kind != Kind.Ok && r.value.len == 0 && r.failure.kind == Kind.InvalidInput && r.offset == off, "sticky error diagnostics")
  require(g.offset == start && g.failed && g.error_offset == off, "sticky iterator state")
 }
}
fn main() {
 end(Grapheme{})
 empty := text.graphemes("")
 end(next_grapheme(&empty))
 end(next_grapheme(&empty))
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
        program += f'cluster(next_grapheme(&g), {literal(value)})\n'
    program += 'end(next_grapheme(&g))\nend(next_grapheme(&g))\n'
    program += f'partial := text.graphemes({literal(b"ab" + bytes([255]))})\n'
    program += 'cluster(next_grapheme(&partial), "a")\n'
    program += '''for repeat in 0..3 {
 r := next_grapheme(&partial)
 require(r.failure.kind != Kind.Ok && r.value.len == 0 && r.failure.kind == Kind.InvalidInput && r.offset == 2 && partial.offset == 1, "sticky after success")
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
                    (work / 'main.dyn').write_text('''use text "std/unicode/text"
    use mem "std/mem"
    fn main() {
     backing: [1+mem.ArenaBufferOverhead]u8
     pad := (16-(#cast(usize,&backing[0])&15))&15
     a := mem.arena_from_buffer(backing[pad..pad+mem.ArenaHeader+1])
     _ = OPERATION catch { #panic("failed") }
    }
    '''.replace('OPERATION', operation))
                    build(work, mode, tree)
                    result = subprocess.run([str(work / 'run')], capture_output=True, timeout=10)
                    assert result.returncode == 101 and b'arena exhausted' in result.stderr, (mode, operation, result)
                print(f'PASS Unicode exhaustion panics {mode} {"tree" if tree else "SSA"}: fold/normalize', flush=True)

if __name__ == '__main__':
    main()
