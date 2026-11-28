#!/usr/bin/env python3
"""Platform-neutral text algorithms: std/text/fuzzy scoring and positions,
std/text/diff line diffs (checked against a reference: every diff applies,
exact diffs are shortest, the edit bound holds and scratch_bytes is enough),
std/text/position line/column offsets in bytes, UTF-16 units and code
points, std/encoding/jsonrpc Content-Length framing, std/net/url file URIs
for Posix and Windows paths, and utf8.truncate. Each program checks for
Linux, macOS and Windows on x86_64 and aarch64, then runs on this host."""
import os
from pathlib import Path
import random
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build' / ('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve())
TARGETS = ('x86_64-linux', 'aarch64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows')


def dyn_string(data):
    out = []
    for byte in data:
        if 32 <= byte < 127 and chr(byte) not in '"\\{}':
            out.append(chr(byte))
        else:
            out.append('\\x%02x' % byte)
    return '"' + ''.join(out) + '"'


def run(name, source):
    with tempfile.TemporaryDirectory(prefix='dyn-text-') as directory:
        root = Path(directory)
        (root / 'main.dyn').write_text(source)
        for target in TARGETS:
            checked = subprocess.run([DYN, 'check', str(root), '--quiet', '--target', target],
                                     capture_output=True, text=True)
            assert checked.returncode == 0, (name, target, checked.stdout + checked.stderr)
        program = root / ('program.exe' if os.name == 'nt' else 'program')
        built = subprocess.run([DYN, 'build', str(root), '--quiet', '--no-cache', '--output', str(program)],
                               capture_output=True, text=True)
        assert built.returncode == 0, (name, built.stdout + built.stderr)
        ran = subprocess.run([str(program)], capture_output=True, timeout=60)
        assert ran.returncode == 0, (name, ran.stdout.decode(errors='replace'), ran.stderr.decode(errors='replace'))
        return ran.stdout.decode()


rng = random.Random(17)

# Fuzzy: hand-written edge cases, then a corpus compared with a reference.
SEPARATORS = set(b' -_/.:(<\\\t')


def fold(byte):
    return byte + 32 if 65 <= byte <= 90 else byte


def reference_score(text, query):
    if not query:
        return 0, []
    total = wanted = 0
    run_on = False
    first = None
    before = 0
    found = []
    for at, byte in enumerate(text):
        if wanted == len(query):
            break
        goal = query[wanted]
        if fold(byte) == fold(goal):
            if first is None:
                first = at
            total += 4
            if at == 0:
                total += 24
            elif before in SEPARATORS or (65 <= byte <= 90 and 97 <= before <= 122):
                total += 12
            if run_on:
                total += 8
            if byte == goal:
                total += 1
            found.append(at)
            run_on = True
            wanted += 1
        else:
            run_on = False
        before = byte
    if wanted < len(query):
        return -1, None
    total -= min(first, 16)
    total -= min(max(len(text) - len(query), 0), 32) // 4
    return max(total, 1), found


alphabet = b'aAbBcCx -_/.:(<'
pairs = [(b'Switch theme', b'sw th'), (b'Switch theme', b'swth'), (b'open_file', b'of'), (b'openFile', b'oF'),
         (b'git: commit', b'gc'), (b'', b'a'), (b'abc', b''), (b'abc', b'abcd'), (b'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaz', b'z')]
for _ in range(300):
    text = bytes(rng.choice(alphabet) for _ in range(rng.randint(0, 24)))
    query = bytes(rng.choice(b'abcABx ') for _ in range(rng.randint(0, 4)))
    pairs.append((text, query))
corpus_texts = ',\n  '.join(dyn_string(text) for text, _ in pairs)
corpus_queries = ',\n  '.join(dyn_string(query) for _, query in pairs)

FUZZY = r'''use fuzzy "std/text/fuzzy"
use utf8 "std/unicode/utf8"
use "std/bytes"
use "std/io"
use "std/panic"
const Texts: [COUNT]str = [
  TEXTS
]
const Queries: [COUNT]str = [
  QUERIES
]
fn main() {
  panic.assert(fuzzy.score("anything", "") == 0, "empty query scores 0")
  panic.assert(fuzzy.score("", "a") == fuzzy.NoMatch, "empty text")
  panic.assert(fuzzy.score("abc", "acb") == fuzzy.NoMatch, "order matters")
  panic.assert(fuzzy.score("ABC", "abc") > 0 && fuzzy.score("abc", "abc") > fuzzy.score("ABC", "abc"), "case bonus")
  panic.assert(fuzzy.score("open file", "of") > fuzzy.score("loft", "of"), "word starts rank higher")
  // Code points, not bytes: e-grave then copyright holds the bytes of e-acute.
  panic.assert(fuzzy.score("\xc3\xa8\xc2\xa9", "\xc3\xa9") == fuzzy.NoMatch, "no match across code points")
  panic.assert(fuzzy.score("caf\xc3\xa9", "\xc3\xa9") > 0, "multibyte match")
  panic.assert(fuzzy.score("\xff", "\xff") > 0 && fuzzy.score("\xff", "\xfe") == fuzzy.NoMatch, "invalid bytes match themselves")
  found: [4]usize
  // "a", e-acute, U+1F600, "b": the emoji starts at byte 3, "b" at 7.
  panic.assert(fuzzy.positions("a\xc3\xa9\xf0\x9f\x98\x80b", "\xf0\x9f\x98\x80b", found[..]) > 0, "astral match")
  panic.assert(found[0] == 3 && found[1] == 7, "astral positions")
  found[0] = 99
  found[1] = 99
  panic.assert(fuzzy.positions("abc", "abd", found[..]) == fuzzy.NoMatch && found[0] == 99 && found[1] == 99, "untouched on no match")
  short: [1]usize
  panic.assert(fuzzy.positions("Switch theme", "sth", short[..]) == fuzzy.score("Switch theme", "sth") && short[0] == 0, "short found")
  panic.assert(fuzzy.word_start("fooBar", 3) && fuzzy.word_start("foo bar", 4) && fuzzy.word_start("x", 0), "word starts")
  panic.assert(!fuzzy.word_start("foobar", 3) && !fuzzy.word_start("x", 1) && !fuzzy.word_start("a\xc3\xa9", 2), "not word starts")
  panic.assert(fuzzy.word_start("\xc3\xa9 x", 3) && fuzzy.word_start("a\\b", 2), "after a multibyte space, after backslash")
  panic.assert(fuzzy.word_prefix_match("Switch theme", "sw th") && fuzzy.word_prefix_match("Switch theme", "  theme "), "word prefixes")
  panic.assert(!fuzzy.word_prefix_match("Switch theme", "wrtie") && !fuzzy.word_prefix_match("Switch theme", "sw x"), "typo")
  panic.assert(!fuzzy.word_prefix_match("Switch theme", "") && !fuzzy.word_prefix_match("Switch theme", "   "), "no words")
  panic.assert(fuzzy.word_prefix_match("openFile", "fi") && !fuzzy.word_prefix_match("openfile", "fi"), "camel words")
  panic.assert(fuzzy.substring_match("Hello World", "O w") && fuzzy.substring_match("abc", "") && fuzzy.substring_match("", ""), "substring")
  panic.assert(!fuzzy.substring_match("ab", "abc") && !fuzzy.substring_match("abc", "ac"), "no substring")
  // UTF-8 truncation.
  panic.assert(bytes.equal(utf8.truncate("a\xc3\xa9", 2), "a") && bytes.equal(utf8.truncate("a\xc3\xa9", 3), "a\xc3\xa9"), "two-byte")
  panic.assert(utf8.truncate("\xf0\x9f\x98\x80", 3).len == 0 && utf8.truncate("\xf0\x9f\x98\x80x", 4).len == 4, "four-byte")
  panic.assert(utf8.truncate("", 5).len == 0 && utf8.truncate("abc", 0).len == 0 && utf8.truncate("abc", 9).len == 3, "bounds")
  panic.assert(utf8.truncate("\x80\x80\x80\x80\x80", 4).len == 4 && utf8.truncate("a\xe2\x82", 2).len == 2, "invalid bytes")
  panic.assert(utf8.truncate("ab\xe4\xb8\xad", 4).len == 2 && utf8.truncate("ab\xe4\xb8\xad", 3).len == 2, "three-byte")
  for text, index in Texts {
    positions: [8]usize
    score := fuzzy.positions(text, Queries[index], positions[..])
    panic.assert(score == fuzzy.score(text, Queries[index]), "positions and score agree")
    io.print("{}", score)
    if score > 0 {
      for at in 0..Queries[index].len {
        io.print(" {}", positions[at])
      }
    }
    io.println("")
  }
}
'''.replace('COUNT', str(len(pairs))).replace('TEXTS', corpus_texts).replace('QUERIES', corpus_queries)

lines = run('fuzzy', FUZZY).splitlines()
assert len(lines) == len(pairs), len(lines)
for (text, query), line in zip(pairs, lines):
    numbers = [int(part) for part in line.split()]
    score, found = reference_score(text, query)
    expected = [score] + (found if score > 0 else [])
    assert numbers == expected, (text, query, numbers, expected)

# Diff: random line texts, each diff checked by applying it.


def split_lines(data):
    return re.findall(rb'[^\n]*\n|[^\n]+$', data)


def shortest(old, new):
    previous = [0] * (len(new) + 1)
    for a in old:
        current = [0]
        for j, b in enumerate(new):
            current.append(previous[j] + 1 if a == b else max(previous[j + 1], current[j]))
        previous = current
    return len(old) + len(new) - 2 * previous[-1]


cases = [(b'', b'', 10), (b'a\nb\n', b'a\nb\n', 10), (b'', b'a\nb\n', 10), (b'a\nb\n', b'', 10),
         (b'a\nb\nc\n', b'x\ny\nz\n', 100), (b'a\nb\nc\n', b'x\ny\nz\n', 2), (b'a\nb', b'a\nb\n', 10),
         (b'a\r\nb\r\n', b'a\nb\n', 10), (b'a\nb\nc\nd\n', b'a\nX\nc\nd\nY\n', 10), (b'a\nb\nc\nd\n', b'a\nX\nc\nd\nY\n', 0),
         (b'same\n' * 50 + b'x\n', b'same\n' * 50 + b'y\n', 1)]
for _ in range(250):
    old = b''.join(rng.choice([b'a\n', b'b\n', b'c\n', b'\n', b'a']) for _ in range(rng.randint(0, 12)))
    new = b''.join(rng.choice([b'a\n', b'b\n', b'c\n', b'\n', b'd\n']) for _ in range(rng.randint(0, 12)))
    cases.append((old, new, rng.choice([0, 1, 2, 3, 5, 8, 100, 100, 100])))

DIFF = r'''use diff "std/text/diff"
use "std/io"
use "std/mem"
use "std/panic"
const Olds: [COUNT]str = [
  OLDS
]
const News: [COUNT]str = [
  NEWS
]
const Bounds: [COUNT]usize = [BOUNDS]
storage: [1048576]u8
fn kind_name(kind: diff.HunkKind) str {
  case kind {
    .Insert => { return "insert" }
    .Delete => { return "delete" }
    .Change => { return "change" }
  }
}
fn main() {
  arena := mem.arena_alloc(0)
  panic.assert(diff.line_count("") == 0 && diff.line_count("a") == 1 && diff.line_count("a\n") == 1 && diff.line_count("a\n\n") == 2, "line_count")
  // One arena for both: the hunks stay valid, with the scratch left in it.
  shared := diff.lines(arena, arena, "a\nb\nc\n", "a\nc\nd\n", 10)
  panic.assert(shared.exact && shared.edits == 2 && shared.hunks.len == 2, "shared arena")
  panic.assert(shared.hunks[0].kind == .Delete && shared.hunks[0].old_start == 1 && shared.hunks[0].new_start == 1, "delete b")
  panic.assert(shared.hunks[1].kind == .Insert && shared.hunks[1].old_start == 3 && shared.hunks[1].new_start == 2, "insert d")
  // A separate scratch is rewound; one that is exactly scratch_bytes is enough.
  for old, index in Olds {
    new := News[index]
    need := diff.scratch_bytes(old, new, Bounds[index]) + mem.ArenaBufferOverhead
    panic.assert(need <= storage.len, "test storage")
    scratch := mem.arena_from_buffer(storage[..need])
    before := mem.arena_used(scratch)
    result := diff.lines(arena, scratch, old, new, Bounds[index])
    panic.assert(mem.arena_used(scratch) == before, "scratch rewound")
    exact: i32 = 0
    if result.exact {
      exact = 1
    }
    io.println("{} {} {} {} {}", exact, result.edits, result.old_lines, result.new_lines, result.hunks.len)
    for hunk in result.hunks {
      io.println("{} {} {} {} {}", kind_name(hunk.kind), hunk.old_start, hunk.old_count, hunk.new_start, hunk.new_count)
    }
  }
}
'''.replace('COUNT', str(len(cases))).replace('OLDS', ',\n  '.join(dyn_string(old) for old, _, _ in cases)) \
   .replace('NEWS', ',\n  '.join(dyn_string(new) for _, new, _ in cases)) \
   .replace('BOUNDS', ', '.join(str(bound) for _, _, bound in cases))

output = run('diff', DIFF).splitlines()
at = 0
inexact = 0
for old, new, bound in cases:
    exact, edits, old_count, new_count, count = map(int, output[at].split())
    at += 1
    old_lines, new_lines = split_lines(old), split_lines(new)
    assert (old_count, new_count) == (len(old_lines), len(new_lines)), (old, new)
    hunks = []
    for _ in range(count):
        kind, os_, oc, ns, nc = output[at].split()
        at += 1
        hunks.append((kind, int(os_), int(oc), int(ns), int(nc)))
    # Apply: hunks in order, separated by equal lines, kinds matching counts.
    rebuilt = []
    old_at = new_at = 0
    for kind, os_, oc, ns, nc in hunks:
        assert kind == ('insert' if oc == 0 else 'delete' if nc == 0 else 'change'), hunks
        assert oc + nc > 0 and os_ - old_at == ns - new_at, hunks
        assert old_at == 0 and new_at == 0 or os_ > old_at, ('hunks touch', old, new, hunks)
        rebuilt += old_lines[old_at:os_]
        rebuilt += new_lines[ns:ns + nc]
        old_at, new_at = os_ + oc, ns + nc
    rebuilt += old_lines[old_at:]
    assert rebuilt == new_lines, (old, new, hunks)
    assert len(old_lines) - old_at == len(new_lines) - new_at, (old, new, hunks)
    best = shortest(old_lines, new_lines)
    assert exact or best > bound, (old, new, bound, best)
    if exact:
        assert edits == best, (old, new, bound, edits, best)
    else:
        inexact += 1
        assert best > bound and count == 1 and hunks[0][0] == 'change', (old, new, bound, best, hunks)
        assert edits == hunks[0][2] + hunks[0][4]
assert at == len(output)
assert inexact > 10, inexact

POSITION = r'''use position "std/text/position"
use "std/panic"
fn offset(text: str, line: usize, column: usize, unit: position.Unit) usize {
  return position.offset_from_position(text, position.Position{ line: line, column: column }, unit) catch 9999
}
fn at(text: str, value: usize, unit: position.Unit, line: usize, column: usize) bool {
  found := position.position_from_offset(text, value, unit)
  return found.line == line && found.column == column
}
fn main() {
  // "a", e-acute, U+1F600, CR LF, "z", U+4E2D: 1 + 2 + 4 + 2 + 1 + 3 bytes.
  text := "a\xc3\xa9\xf0\x9f\x98\x80\r\nz\xe4\xb8\xad"
  panic.assert(at(text, 7, .Utf16, 0, 4) && at(text, 7, .Codepoint, 0, 3) && at(text, 7, .Byte, 0, 7), "units")
  panic.assert(offset(text, 0, 4, .Utf16) == 7 && offset(text, 0, 3, .Codepoint) == 7 && offset(text, 0, 7, .Byte) == 7, "offsets")
  panic.assert(offset(text, 0, 3, .Utf16) == 9999, "between surrogates")
  panic.assert(offset(text, 0, 2, .Byte) == 9999, "inside a UTF-8 sequence")
  panic.assert(offset(text, 0, 99, .Utf16) == 7, "past the line end clamps before CR LF")
  panic.assert(offset(text, 1, 2, .Utf16) == text.len && offset(text, 1, 9, .Utf16) == text.len, "last line")
  panic.assert(offset(text, 2, 0, .Utf16) == 9999 && offset(text, 8, 0, .Utf16) == 9999, "no such line")
  panic.assert(at(text, 5, .Utf16, 0, 2) && at(text, 2, .Utf16, 0, 1), "inside a code point rounds down")
  panic.assert(at(text, 8, .Utf16, 0, 4) && at(text, 9, .Utf16, 1, 0) && at(text, 999, .Utf16, 1, 2), "CR LF and past the end")
  // A lone CR ends a line, as LSP says; "a\n" has an empty line 1.
  panic.assert(offset("a\rb", 1, 0, .Utf16) == 2 && at("a\rb", 3, .Utf16, 1, 1), "lone CR")
  panic.assert(offset("a\n", 1, 0, .Utf16) == 2 && offset("a\n", 2, 0, .Utf16) == 9999 && at("a\n", 2, .Utf16, 1, 0), "final newline")
  panic.assert(offset("a\n\nb", 1, 5, .Utf16) == 2 && offset("a\n\nb", 2, 1, .Utf16) == 4, "empty line")
  panic.assert(offset("", 0, 0, .Utf16) == 0 && offset("", 0, 3, .Utf16) == 0 && offset("", 1, 0, .Utf16) == 9999 && at("", 5, .Utf16, 0, 0), "empty")
  // U+FFFF is one UTF-16 unit, U+10000 the first that takes two.
  panic.assert(at("\xef\xbf\xbf", 3, .Utf16, 0, 1) && at("\xf0\x90\x80\x80", 4, .Utf16, 0, 2), "BMP edge")
  panic.assert(offset("\xf0\x90\x80\x80!", 0, 2, .Utf16) == 4 && offset("\xf0\x90\x80\x80!", 0, 1, .Utf16) == 9999, "astral edge")
  panic.assert(at("\xff\xfe", 2, .Utf16, 0, 2) && offset("\xff\xfe", 0, 1, .Utf16) == 1, "invalid bytes are one unit")
  // Every code point boundary round-trips, in every unit.
  sample := "x\xf0\x90\x80\x80y\n\xc3\xa9\r\n\r\xf0\x9f\x98\x80\n"
  for unit in [position.Unit.Byte, position.Unit.Utf16, position.Unit.Codepoint] {
    for value in 0..sample.len + 1 {
      boundary := value == sample.len || (sample[value] & 0xc0) != 0x80
      between := value > 0 && value < sample.len && sample[value - 1] == '\r' && sample[value] == '\n'
      if !boundary || between { continue }
      found := position.position_from_offset(sample, value, unit)
      panic.assert((position.offset_from_position(sample, found, unit) catch 9999) == value, "round trip")
    }
  }
  // A cursor resolves ascending positions, and goes back when asked.
  cursor := position.cursor("one\ntwo\nthree")
  panic.assert((position.cursor_offset(&cursor, position.Position{ line: 1, column: 1 }, .Utf16) catch 0) == 5, "cursor 1")
  panic.assert((position.cursor_offset(&cursor, position.Position{ line: 2, column: 5 }, .Utf16) catch 0) == 13, "cursor 2")
  panic.assert((position.cursor_offset(&cursor, position.Position{ line: 0, column: 2 }, .Utf16) catch 0) == 2, "cursor back")
  panic.assert((position.cursor_offset(&cursor, position.Position{ line: 3, column: 0 }, .Utf16) catch 9999) == 9999, "cursor past")
  panic.assert((position.cursor_offset(&cursor, position.Position{ line: 2, column: 0 }, .Utf16) catch 0) == 8, "cursor after failure")
}
'''
run('position', POSITION)

JSONRPC = r'''use jsonrpc "std/encoding/jsonrpc"
use parse "std/parse"
use "std/bytes"
use "std/panic"
fn failure(decoder: *jsonrpc.Decoder, input: str) parse.ParseErr {
  _ = jsonrpc.decode(decoder, input) catch err { return err }
  #panic("decode should fail")
}
fn invalid(input: str) usize {
  decoder := jsonrpc.Decoder{}
  case failure(&decoder, input) {
    .Invalid(offset) => { return offset }
    _ => { #panic("expected Invalid") }
  }
}
fn too_large(decoder: *jsonrpc.Decoder, input: str) bool {
  case failure(decoder, input) {
    .TooLarge(_) => { return true }
    _ => { return false }
  }
}
fn main() {
  zero := jsonrpc.header(0)
  panic.assert(bytes.equal(zero.bytes[..zero.length], "Content-Length: 0\r\n\r\n"), "header 0")
  big := jsonrpc.header(18446744073709551615)
  panic.assert(big.length == jsonrpc.HeaderLimit || #sizeof(usize) == 4, "longest header")
  some := jsonrpc.header(1234)
  panic.assert(bytes.equal(some.bytes[..some.length], "Content-Length: 1234\r\n\r\n"), "header 1234")
  // Two messages in one buffer, then each byte of a message arriving alone.
  stream := "Content-Length: 2\r\n\r\n{}content-length:  3 \r\nContent-Type: application/vscode-jsonrpc; charset=utf-8\r\n\r\n[1]"
  decoder := jsonrpc.Decoder{}
  first := jsonrpc.decode(&decoder, stream) catch { #panic("first") }
  panic.assert(first.ready && bytes.equal(first.body, "{}") && first.length == 23, "first frame")
  second := jsonrpc.decode(&decoder, stream[first.length..]) catch { #panic("second") }
  panic.assert(second.ready && bytes.equal(second.body, "[1]") && first.length + second.length == stream.len, "second frame")
  message := "Content-Length: 5\r\n\r\nhello"
  split := jsonrpc.Decoder{}
  for end in 0..message.len {
    partial := jsonrpc.decode(&split, message[..end]) catch { #panic("partial") }
    panic.assert(!partial.ready, "not ready early")
    if end >= 21 {
      panic.assert(partial.needed == message.len, "needed once the header is read")
    } else {
      panic.assert(partial.needed == 0, "needed unknown")
    }
  }
  whole := jsonrpc.decode(&split, message) catch { #panic("whole") }
  panic.assert(whole.ready && bytes.equal(whole.body, "hello"), "split frame")
  empty := jsonrpc.decode(&split, "Content-Length: 0\r\n\r\n") catch { #panic("empty body") }
  panic.assert(empty.ready && empty.body.len == 0, "empty body")
  // Malformed headers fail with Invalid at the offending byte.
  panic.assert(invalid("X: y\r\n\r\n{}") == 0, "missing length")
  panic.assert(invalid("Content-Length: 2\r\nContent-Length: 2\r\n\r\n{}") == 19, "duplicate length")
  panic.assert(invalid("Content-Length: 2x\r\n\r\n{}") == 17, "not a number")
  panic.assert(invalid("Content-Length: -2\r\n\r\n{}") == 16, "negative")
  panic.assert(invalid("Content-Length:\r\n\r\n") == 15, "no value")
  panic.assert(invalid("Content-Length 2\r\n\r\n{}") == 14, "no colon")
  panic.assert(invalid("Content-Length: 2\nX: y\r\n\r\n{}") == 17, "bare LF")
  panic.assert(invalid("\r\n\r\n") == 0, "no fields")
  // Oversized headers and bodies fail with TooLarge, and stay failed.
  long := jsonrpc.Decoder{}
  filler: [9000]u8
  for *byte in filler {
    byte.* = 'x'
  }
  panic.assert(too_large(&long, filler[..]), "unterminated header")
  panic.assert(too_large(&long, "Content-Length: 2\r\n\r\n{}"), "failure is sticky")
  small := jsonrpc.Decoder{ max_header: 32, max_body: 100 }
  panic.assert(too_large(&small, "Content-Length: 2\r\nX-Padding: 0123456789\r\n\r\n{}"), "header past max_header")
  limited := jsonrpc.Decoder{ max_body: 100 }
  panic.assert(too_large(&limited, "Content-Length: 101\r\n\r\n"), "body past max_body")
  huge := jsonrpc.Decoder{}
  panic.assert(too_large(&huge, "Content-Length: 99999999999999999999999999\r\n\r\n"), "overflow")
  fits := jsonrpc.Decoder{ max_body: 100 }
  exactly := jsonrpc.decode(&fits, "Content-Length: 100\r\n\r\n") catch { #panic("max_body fits") }
  panic.assert(!exactly.ready && exactly.needed == 123, "max_body itself fits")
  fresh := jsonrpc.Decoder{}
  #init(&long)
  again := jsonrpc.decode(&long, "Content-Length: 2\r\n\r\n{}") catch { #panic("init restarts") }
  panic.assert(again.ready && long.max_header == fresh.max_header, "init restarts")
}
'''
run('jsonrpc', JSONRPC)

URL = r'''use url "std/net/url"
use parse "std/parse"
use "std/bytes"
use "std/mem"
use "std/panic"
arena: *mem.Arena
fn uri(path: str, style: url.PathStyle) str {
  return url.file_uri_from_path(arena, path, style) catch { return "!" }
}
fn path(text: str, style: url.PathStyle) str {
  return url.path_from_file_uri(arena, text, style) catch { return "!" }
}
fn path_failure(text: str, style: url.PathStyle) parse.ParseErr {
  mark := mem.arena_used(arena)
  _ = url.path_from_file_uri(arena, text, style) catch err {
    panic.assert(mem.arena_used(arena) == mark, "nothing pushed on failure")
    return err
  }
  #panic("path should fail")
}
fn invalid_at(err: parse.ParseErr) usize {
  case err {
    .Invalid(offset) => { return offset }
    _ => { return 9999 }
  }
}
fn unsupported_at(err: parse.ParseErr) usize {
  case err {
    .Unsupported(offset) => { return offset }
    _ => { return 9999 }
  }
}
fn main() {
  arena = mem.arena_alloc(0)
  posix := url.PathStyle.Posix
  windows := url.PathStyle.Windows
  panic.assert(bytes.equal(uri("/tmp/a #\xc3\xa9.dyn", posix), "file:///tmp/a%20%23%C3%A9.dyn"), "posix uri")
  panic.assert(bytes.equal(path("file:///tmp/a%20%23%C3%A9.dyn", posix), "/tmp/a #\xc3\xa9.dyn"), "posix path")
  panic.assert(bytes.equal(uri("/", posix), "file:///") && bytes.equal(path("file:///", posix), "/"), "root")
  panic.assert(bytes.equal(uri("/a~b-c_d.e/%", posix), "file:///a~b-c_d.e/%25"), "unreserved and percent")
  panic.assert(bytes.equal(path("FILE:/a", posix), "/a") && bytes.equal(path("file://LocalHost/a", posix), "/a"), "scheme case, localhost")
  panic.assert(bytes.equal(path("file:///a%2fb%e4%B8%ad", posix), "/a/b\xe4\xb8\xad"), "lower and upper hex")
  panic.assert(bytes.equal(uri("relative", posix), "!") && bytes.equal(uri("", posix), "!") && bytes.equal(uri("/a\x00b", posix), "!"), "posix invalid paths")
  panic.assert(invalid_at(path_failure("file:///tmp/%00x", posix)) == 12, "NUL escape")
  panic.assert(invalid_at(path_failure("file:///tmp/%4", posix)) == 12 && invalid_at(path_failure("file:///%zz", posix)) == 8, "malformed escape")
  panic.assert(invalid_at(path_failure("http:///a", posix)) == 0 && invalid_at(path_failure("file:a", posix)) == 5, "scheme and path")
  panic.assert(invalid_at(path_failure("file:///a?q", posix)) == 9 && invalid_at(path_failure("file:///a#f", posix)) == 9, "query and fragment")
  panic.assert(invalid_at(path_failure("file://u@h/a", posix)) == 8 && invalid_at(path_failure("file://h:1/a", posix)) == 8, "userinfo and port")
  panic.assert(unsupported_at(path_failure("file://host/path", posix)) == 7, "remote host under posix")
  // Windows: drive letters, separators, UNC and long-path prefixes.
  panic.assert(bytes.equal(uri("C:\\Users\\me\\a b.txt", windows), "file:///C:/Users/me/a%20b.txt"), "drive uri")
  panic.assert(bytes.equal(path("file:///C:/Users/me/a%20b.txt", windows), "C:\\Users\\me\\a b.txt"), "drive path")
  panic.assert(bytes.equal(uri("c:/x/y", windows), "file:///c:/x/y") && bytes.equal(uri("C:\\", windows), "file:///C:/"), "forward slashes, root")
  panic.assert(bytes.equal(path("file:///c%3A/x", windows), "c:\\x") && bytes.equal(path("file:///C:", windows), "C:\\"), "escaped colon, bare drive")
  panic.assert(bytes.equal(path("file://localhost/D:/x", windows), "D:\\x"), "localhost drive")
  panic.assert(bytes.equal(uri("\\\\server\\share\\a b", windows), "file://server/share/a%20b"), "unc uri")
  panic.assert(bytes.equal(path("file://server/share/a%20b", windows), "\\\\server\\share\\a b"), "unc path")
  panic.assert(bytes.equal(uri("\\\\?\\C:\\long\\x", windows), "file:///C:/long/x"), "long drive prefix")
  panic.assert(bytes.equal(uri("\\\\?\\UNC\\srv\\sh\\x", windows), "file://srv/sh/x"), "long unc prefix")
  panic.assert(bytes.equal(uri("C:x", windows), "!") && bytes.equal(uri("\\x", windows), "!") && bytes.equal(uri("x\\y", windows), "!"), "windows relative")
  panic.assert(bytes.equal(uri("\\\\\\x", windows), "!") && bytes.equal(uri("\\\\.\\pipe\\x", windows), "!"), "empty host, device path")
  panic.assert(unsupported_at(path_failure("file:///home/x", windows)) == 7, "no drive under windows")
  // Round trips.
  for original in ["/", "/a/b c/\xf0\x9f\x98\x80", "/100%/?#[]@!$&'()*+,;="] {
    panic.assert(bytes.equal(path(uri(original, posix), posix), original), "posix round trip")
  }
  for original in ["C:\\", "Z:\\a\\b c\\\xc3\xa9", "\\\\h\\s\\x;y", "C:\\100%\\#"] {
    panic.assert(bytes.equal(path(uri(original, windows), windows), original), "windows round trip")
  }
}
'''
run('url', URL)

print(f'PASS text algorithms: fuzzy ({len(pairs)} scored), diff ({len(cases)} applied, {inexact} past the bound), '
      'positions, Content-Length framing, file URIs, utf8.truncate; six targets checked')
