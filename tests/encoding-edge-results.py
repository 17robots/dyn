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


SOURCE = '''use "std/encoding/base64" b
use "std/encoding/hex" h
use "std/encoding" codec
use "std/errors" errors
use "std/mem" mem
use "std/bytes" bytes
fn good(raw: []const u8, hx: []const u8, upper: []const u8, b64: []const u8) {
  backing: [4096]u8 = []
  mem.fill(backing[..], 99)
  a := mem.arena_from_buffer(backing[..])
  _ = mem.push_bytes_uninit(&a, 7)
  a.poison_on_rewind = true
  x: h.Decoded = h.decode(&a, hx)
  y: b.Decoded = b.decode(&a, b64)
  z := h.decode(&a, upper)
  if !x.ok || !y.ok || !z.ok || !bytes.equal(x.value, raw) || !bytes.equal(y.value, raw) || !bytes.equal(z.value, raw) { #panic("decode oracle") }
  if x.kind != errors.Kind.None || y.kind != errors.Kind.None || z.kind != errors.Kind.None ||
     x.error != 0 || y.error != 0 || z.error != 0 || x.offset != 0 || y.offset != 0 || z.offset != 0 ||
     x.detail != codec.ErrorKind.None || y.detail != codec.ErrorKind.None || z.detail != codec.ErrorKind.None { #panic("success diagnostics") }
  if mem.arena_mark(&a) != 7 + 3 * #len(raw) { #panic("exact decode allocation") }
  if !bytes.equal(h.encode(&a, raw, false), hx) || !bytes.equal(h.encode(&a, raw, true), upper) || !bytes.equal(b.encode(&a, raw), b64) { #panic("encode oracle") }
  for c in backing[..7] { if c != 99 { #panic("success changed prefix") } }
}
fn bad(input: []const u8, off: usize, hex: bool) {
  backing: [128]u8 = []
  mem.fill(backing[..], 99)
  a := mem.arena_from_buffer(backing[..])
  _ = mem.push_bytes_uninit(&a, 7)
  a.poison_on_rewind = true
  if hex {
    r := h.decode(&a, input)
    if r.ok || #len(r.value) != 0 || r.kind != errors.Kind.InvalidInput || r.error != 0 || r.offset != off || r.detail != codec.ErrorKind.InvalidInput { #panic("hex invalid diagnostics") }
  } else {
    r := b.decode(&a, input)
    if r.ok || #len(r.value) != 0 || r.kind != errors.Kind.InvalidInput || r.error != 0 || r.offset != off || r.detail != codec.ErrorKind.InvalidInput { #panic("base64 invalid diagnostics") }
  }
  if mem.arena_mark(&a) != 7 { #panic("invalid rollback") }
  for c in backing { if c != 99 { #panic("invalid touched dirty arena") } }
}
fn overlap(hex: bool, invalid: bool, start: usize) {
  backing: [32]u8 = []
  snapshot: [32]u8 = []
  mem.fill(backing[..], 99)
  input := "AAAA"
  if hex { input = "6162" }
  if invalid { input = "!!!!" }
  _ = mem.copy(backing[start..], input)
  _ = mem.copy(snapshot[..], backing[..])
  a := mem.arena_from_buffer(backing[..])
  _ = mem.push_bytes_uninit(&a, 4)
  a.poison_on_rewind = true
  detail := codec.ErrorKind.Overlap
  if invalid { detail = codec.ErrorKind.InvalidInput }
  if hex {
    r := h.decode(&a, backing[start..start + 4])
    if r.ok || #len(r.value) != 0 || r.kind != errors.Kind.InvalidInput || r.error != 0 || r.offset != 0 || r.detail != detail { #panic("hex overlap preflight") }
  } else {
    r := b.decode(&a, backing[start..start + 4])
    if r.ok || #len(r.value) != 0 || r.kind != errors.Kind.InvalidInput || r.error != 0 || r.offset != 0 || r.detail != detail { #panic("base64 overlap preflight") }
  }
  if mem.arena_mark(&a) != 4 || !bytes.equal(backing[..], snapshot[..]) { #panic("overlap changed source or arena") }
}
fn main() {
  z := b.Decoded{}
  q := h.Decoded{}
  if z.ok || q.ok || #len(z.value) != 0 || #len(q.value) != 0 ||
     z.kind != errors.Kind.None || q.kind != errors.Kind.None || z.error != 0 || q.error != 0 ||
     z.offset != 0 || q.offset != 0 || z.detail != codec.ErrorKind.None || q.detail != codec.ErrorKind.None { #panic("zero initialization") }
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
  for invalid in [false, true] {
    overlap(hex, invalid, 2)
    overlap(hex, invalid, 4)
    overlap(hex, invalid, 5)
  }
}
// Malformed input is validated even when no output storage remains.
empty_backing: [0]u8 = []
a := mem.arena_from_buffer(empty_backing[..])
x := b.decode(&a, "AAAA!!!!")
y := h.decode(&a, "6162!!")
if x.ok || y.ok || x.offset != 4 || y.offset != 4 || x.error != 0 || y.error != 0 ||
   x.kind != errors.Kind.InvalidInput || y.kind != errors.Kind.InvalidInput ||
   x.detail != codec.ErrorKind.InvalidInput || y.detail != codec.ErrorKind.InvalidInput ||
   #len(x.value) != 0 || #len(y.value) != 0 || mem.arena_mark(&a) != 0 { #panic("validation before exhaustion") }
x = b.decode(&a, "")
y = h.decode(&a, "")
if !x.ok || !y.ok || #len(x.value) != 0 || #len(y.value) != 0 || x.error != 0 || y.error != 0 ||
   x.kind != errors.Kind.None || y.kind != errors.Kind.None || x.offset != 0 || y.offset != 0 ||
   x.detail != codec.ErrorKind.None || y.detail != codec.ErrorKind.None || mem.arena_mark(&a) != 0 { #panic("empty at capacity") }
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
                (work / 'main.dyn').write_text(f'''use "std/mem" mem
use "std/encoding/{module}" codec
fn main() {{
  backing: [1]u8 = []
  arena := mem.arena_from_buffer(backing[..])
  _ = codec.decode(&arena, "{encoded}")
}}
''')
                build(work, mode)
                result = subprocess.run([str(work / 'program')], capture_output=True, timeout=10)
                assert result.returncode != 0, (module, mode, 'exhaustion returned')
                assert b'arena exhausted' in result.stderr, (module, mode, result.stderr)
                print(f'PASS {module} exhaustion panic {mode}', flush=True)
                arguments = '&arena, backing[..1], false' if module == 'hex' else '&arena, backing[..1]'
                (work / 'main.dyn').write_text(f'''use "std/mem" mem
use "std/encoding/{module}" codec
fn main() {{
  backing: [32]u8 = []
backing[0] = 'a'
  arena := mem.arena_from_buffer(backing[..])
  _ = codec.encode({arguments})
}}
''')
                build(work, mode)
                result = subprocess.run([str(work / 'program')], capture_output=True, timeout=10)
                assert result.returncode != 0 and b'overlap' in result.stderr, (module, mode, result)



if __name__ == '__main__':
    main()
