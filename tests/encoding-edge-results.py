#!/usr/bin/env python3
"""Arena base64/hex result contracts against bounded Python codec oracles.

Only public arena producers are exercised: the private codec helpers' shared
Result is intentionally not the public Decoded contract. No test registration
is performed here. Every compiler and executable invocation has a timeout.
"""
import base64
import os
from pathlib import Path
import random
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())


def literal(data):
    return '"' + ''.join('\\x%02x' % byte for byte in data) + '"'


SOURCE = '''use parse "std/parse"
use b "std/encoding/base64"
use h "std/encoding/hex"
use mem "std/mem"
use bytes "std/bytes"
// failed: the decode failed with Invalid at offset.
struct Decoded { value: []u8, failed: bool, offset: usize }
fn failure(err: parse.ParseErr) Decoded {
  case err {
    .Invalid(at) => { return Decoded{ failed: true, offset: at } }
    .TooLarge(at) => { #panic("unexpected TooLarge") }
    .Unsupported(at) => { #panic("unexpected TooLarge") }
  }
}
fn hd(a: *mem.Arena, input: []const u8) Decoded {
  value := h.decode(a, input) catch err { return failure(err) }
  return Decoded{ value: value }
}
fn bd(a: *mem.Arena, input: []const u8) Decoded {
  value := b.decode(a, input) catch err { return failure(err) }
  return Decoded{ value: value }
}
fn good(raw: []const u8, hx: []const u8, upper: []const u8, b64: []const u8) {
  backing: [4096 + mem.ArenaBufferOverhead]u8
  mem.fill(backing[..], 99)
  a := mem.arena_from_buffer(backing[..])
  prefix := mem.push_bytes(a, 7)
  a.poison_on_rewind = true
  x := hd(a, hx)
  y := bd(a, b64)
  z := hd(a, upper)
  if x.failed || y.failed || z.failed || !bytes.equal(x.value, raw) || !bytes.equal(y.value, raw) || !bytes.equal(z.value, raw) { #panic("decode oracle") }
  if mem.arena_mark(a) != mem.ArenaHeader + 7 + 3 * raw.len { #panic("exact decode allocation") }
  if !bytes.equal(h.encode(a, raw, false), hx) || !bytes.equal(h.encode(a, raw, true), upper) || !bytes.equal(b.encode(a, raw), b64) { #panic("encode oracle") }
  for c in prefix { if c != 99 { #panic("success changed prefix") } }
}
fn bad(input: []const u8, off: usize, hex: bool) {
  backing: [128 + mem.ArenaBufferOverhead]u8
  mem.fill(backing[..], 99)
  a := mem.arena_from_buffer(backing[..])
  prefix := mem.push_bytes(a, 7)
  a.poison_on_rewind = true
  if hex {
    r := hd(a, input)
    if r.value.len != 0 || r.offset != off || !r.failed { #panic("hex invalid diagnostics") }
  } else {
    r := bd(a, input)
    if r.value.len != 0 || r.offset != off || !r.failed { #panic("base64 invalid diagnostics") }
  }
  if mem.arena_mark(a) != mem.ArenaHeader + 7 { #panic("invalid rollback") }
  for c in a.data[mem.ArenaHeader..] { if c != 99 { #panic("invalid touched dirty arena") } }
}
// Invalid input in the arena's free space fails before the overlap check;
// valid input there panics (checked by its own program below).
fn overlap(hex: bool, start: usize) {
  backing: [32 + mem.ArenaBufferOverhead]u8
  snapshot: [32]u8
  mem.fill(backing[..], 99)
  input := "!!!!"
  a := mem.arena_from_buffer(backing[..])
  payload := a.data[mem.ArenaHeader..mem.ArenaHeader + 32]
  _ = mem.copy(payload[start..], input)
  _ = mem.copy(snapshot[..], payload)
  _ = mem.push_bytes(a, 4)
  a.poison_on_rewind = true
  if hex {
    r := hd(a, payload[start..start + 4])
    if r.value.len != 0 || r.offset != 0 || !r.failed { #panic("hex overlap preflight") }
  } else {
    r := bd(a, payload[start..start + 4])
    if r.value.len != 0 || r.offset != 0 || !r.failed { #panic("base64 overlap preflight") }
  }
  if mem.arena_mark(a) != mem.ArenaHeader + 4 || !bytes.equal(payload, snapshot[..]) { #panic("overlap changed source or arena") }
}
fn main() {
  z := Decoded{}
  if z.failed || z.value.len != 0 || z.offset != 0 { #panic("zero initialization") }
'''


def source():
    program = SOURCE
    rng = random.Random(971)
    # RFC-style short goldens, all byte values, and deterministic size boundaries.
    cases = [b'', b'f', b'fo', b'foo', b'foob', b'fooba', b'foobar', bytes(range(256))]
    cases += [rng.randbytes(n) for n in [*range(1, 66), 127, 128, 255]]
    for raw in cases:
        hx = raw.hex()
        encoded = base64.b64encode(raw)
        assert bytes.fromhex(hx) == raw
        assert base64.b64decode(encoded, validate=True) == raw
        program += f'good({literal(raw)}, "{hx}", "{hx.upper()}", {literal(encoded)})\n'
    # Invalid byte at every position, including after a valid complete group.
    # Iterate all non-alphabet bytes, rather than only printable punctuation.
    for alphabet, valid, is_hex in [
        (b'0123456789abcdefABCDEF', b'01234567', True),
        (b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=', b'AAAAAAAA', False),
    ]:
        for byte in range(256):
            if byte in alphabet:
                continue
            for position in range(len(valid)):
                malformed = valid[:position] + bytes([byte]) + valid[position + 1:]
                program += f'bad({literal(malformed)}, {position}, {str(is_hex).lower()})\n'
    malformed64 = [
        ('!', 1), ('A', 1), ('AA', 2), ('AAA', 3), ('AAAAA', 5),
        ('=AAA', 0), ('A=AA', 1), ('AA=A', 3), ('====', 0), ('A===', 1),
        ('AA==AAAA', 2), ('AAA=AAAA', 3), ('AAAA=AAA', 4), ('AAAAA=AA', 5),
        ('AAAAAA=A', 7), ('AAAA====', 4),
    ]
    for value, offset in malformed64:
        program += f'bad({literal(value.encode())}, {offset}, false)\n'
    for value in [b'0', b'00f', b'00000', b'0000000']:
        program += f'bad({literal(value)}, {len(value)}, true)\n'
    alphabet = b'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    # All forbidden unused-bit patterns in both padded tail shapes, with/without prefix.
    for prefix in [b'', b'AAAA']:
        for index, byte in enumerate(alphabet):
            if index % 16:
                value = prefix + b'Z' + bytes([byte]) + b'=='
                program += f'bad({literal(value)}, {len(prefix) + 1}, false)\n'
            if index % 4:
                value = prefix + b'Zm' + bytes([byte]) + b'='
                program += f'bad({literal(value)}, {len(prefix) + 2}, false)\n'
    program += '''for hex in [false, true] {
  overlap(hex, 2)
  overlap(hex, 4)
  overlap(hex, 5)
}
// Malformed input is validated even when no output storage remains.
empty_backing: [mem.ArenaBufferOverhead]u8
a := mem.arena_from_buffer(empty_backing[..])
a = mem.arena_from_buffer(a.data[..mem.ArenaHeader])
x := bd(a, "AAAA!!!!")
y := hd(a, "6162!!")
if x.offset != 4 || y.offset != 4 || !x.failed || !y.failed ||
   x.value.len != 0 || y.value.len != 0 || mem.arena_mark(a) != mem.ArenaHeader { #panic("validation before exhaustion") }
x = bd(a, "")
y = hd(a, "")
if x.failed || y.failed || x.value.len != 0 || y.value.len != 0 || mem.arena_mark(a) != mem.ArenaHeader { #panic("empty at capacity") }
}
'''
    return program, len(cases)


def build(work, mode):
    subprocess.run([DYN, 'build', str(work), '--' + mode, '--no-cache', '--quiet',
                    '--output', str(work / 'program')], cwd=ROOT.parent, check=True, timeout=120)


def main():
    program, count = source()
    with tempfile.TemporaryDirectory(prefix='dyn-encoding-edges-') as directory:
        work = Path(directory)
        for mode in ('debug', 'release'):
            (work / 'main.dyn').write_text(program)
            build(work, mode)
            subprocess.run([str(work / 'program')], check=True, capture_output=True, timeout=15)
            print(f'PASS encoding edges {mode}: {count} oracle cases, invalid bytes/positions, tails, rollback, overlap', flush=True)
            for module, encoded in [('base64', 'AAAA'), ('hex', '6162'), ('base32', 'MZXQ====')]:
                (work / 'main.dyn').write_text(f'''use mem "std/mem"
use codec "std/encoding/{module}"
fn main() {{
  backing: [mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(backing[..])
  arena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader])
  _ = codec.decode(arena, "{encoded}") catch {{ return }}
}}
''')
                build(work, mode)
                result = subprocess.run([str(work / 'program')], capture_output=True, timeout=10)
                assert result.returncode != 0, (module, mode, 'exhaustion returned')
                assert b'arena exhausted' in result.stderr, (module, mode, result.stderr)
                print(f'PASS {module} exhaustion panic {mode}', flush=True)
                # Valid input in the arena's free space is a caller bug: decode panics.
                (work / 'main.dyn').write_text(f'''use mem "std/mem"
use codec "std/encoding/{module}"
fn main() {{
  backing: [32 + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(backing[..])
  payload := arena.data[mem.ArenaHeader..mem.ArenaHeader + 32]
  _ = mem.copy(payload[4..], "{encoded}")
  _ = codec.decode(arena, payload[4..4 + {len(encoded)}]) catch {{ return }}
}}
''')
                build(work, mode)
                result = subprocess.run([str(work / 'program')], capture_output=True, timeout=10)
                assert result.returncode != 0 and b'overlaps arena output' in result.stderr, (module, mode, result.stderr)
                arguments = 'arena, input, false' if module == 'hex' else 'arena, input'
                (work / 'main.dyn').write_text(f'''use mem "std/mem"
use codec "std/encoding/{module}"
fn main() {{
  backing: [32 + mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(backing[..])
  input := arena.data[mem.ArenaHeader..mem.ArenaHeader+1]
  input[0] = 'a'
  _ = codec.encode({arguments})
}}
''')
                build(work, mode)
                result = subprocess.run([str(work / 'program')], capture_output=True, timeout=10)
                assert result.returncode != 0 and b'overlap' in result.stderr, (module, mode, result)



if __name__ == '__main__':
    main()
