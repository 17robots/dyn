#!/usr/bin/env python3
"""JSON owned-string fast path: independent expected bytes, errors and rollback."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()

def literal(data):
    return '[' + ','.join(str(b) for b in data) + ']'

valid = [
    (b'""', b''), (b'"plain ASCII"', b'plain ASCII'),
    (b'"' + b'x' * 4096 + b'"', b'x' * 4096),
    (b'"\\\"\\\\\\/\\b\\f\\n\\r\\t"', bytes([34, 92, 47, 8, 12, 10, 13, 9])),
    (b'"\\u0000\\u007f\\u0080\\u07ff\\u0800"', '\0\x7f\x80\u07ff\u0800'.encode()),
    (b'"\\ud83d\\ude00"', '😀'.encode()),
    ('"café ☃ 😀"'.encode(), 'café ☃ 😀'.encode()),
    (b'"ascii\\u00e9 tail"', 'asciié tail'.encode()),
]
# Exercise the scanner threshold and decoder resumption after an ASCII block.
valid += [(b'"' + b'x' * n + b'"', b'x' * n) for n in (14, 15, 16, 17, 31, 32)]
valid += [(b'"' + b'x' * 16 + b'\\u00e9"', b'x' * 16 + 'é'.encode()),
          (b'"' + b'x' * 16 + 'é'.encode() + b'"', b'x' * 16 + 'é'.encode())]
invalid = [b'"unterminated', b'"bad\\q"', b'"bad\\"', b'"\\u12"',
           b'"\\u00xz"', b'"\\ud800"', b'"\\udc00"', b'"\\ud800\\u0041"',
           b'"\xc0\xaf"', b'"\xed\xa0\x80"', b'"\xf4\x90\x80\x80"',
           b'"\xe2\x82"', b'"\x80"', b'"\\\xff"']
invalid += [b'"a' + bytes([c]) + b'b"' for c in range(32)]
invalid += [b'"' + b'a' * 16 + tail for tail in (b'\\q"', b'\xc0\xaf"', b'\x00"', b'')]

checks = []
# Depth rejection and rollback do not depend on the optimized string route.
deep = b'[' * 257 + b'"plain"' + b']' * 257
checks.append(f'''  if true {{
    data: [{len(deep)}]u8 = {literal(deep)}
    result := json.parse(arena, data[..])
    require(!result.ok && result.detail == json.ErrorKind.Syntax && mem.arena_mark(arena) == mem.arena_start(arena), "depth rollback")
  }}''')
for n, (raw, expected) in enumerate(valid):
    # Both object keys and values must survive mutation of all source bytes.
    doc = b'{' + raw + b':' + raw + b'}'
    checks.append(f'''  if true {{
    data: [{len(doc)}]u8 = {literal(doc)}
    expected: [{len(expected)}]u8 = {literal(expected)}
    result := json.parse(arena, data[..])
    require(result.ok, "valid {n}")
    member := result.root.first
    for i in 0..#len(data) {{ data[i] = 255 }}
    require(mem.equal(member.key, expected[..]) && mem.equal(member.text, expected[..]), "owned key/value {n}")
    mem.arena_reset(arena)
  }}''')
for n, raw in enumerate(invalid):
    checks.append(f'''  if true {{
    data: [{len(raw)}]u8 = {literal(raw)}
    mark := mem.arena_mark(arena)
    result := json.parse(arena, data[..])
    require(!result.ok && result.offset == 1 && result.detail == json.ErrorKind.Syntax && json.is_missing(result.root), "invalid {n}")
    require(mem.arena_mark(arena) == mark, "rollback {n}")
  }}''')
source = '''use "std/encoding/json" json
use "std/mem" mem
fn require(ok: bool, message: []const u8) { if !ok { #panic(message) } }
fn main() {
  arena := mem.arena_create(0)
  defer mem.arena_release(arena)
''' + '\n'.join(checks) + '''
  trailing := json.parse(arena, "\\\"abc\\\" x")
  require(!trailing.ok && trailing.offset == 6 && trailing.detail == json.ErrorKind.TrailingData && mem.arena_mark(arena) == mem.arena_start(arena), "trailing rollback")
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-json-string-') as directory:
    work = Path(directory)
    project = work / 'main'
    project.mkdir()
    (project / 'main.dyn').write_text(source)
    capacity = work / 'capacity'
    capacity.mkdir()
    (capacity / 'main.dyn').write_text('use "std/encoding/json" json\nuse "std/mem" mem\nfn main() {\n  backing: [2+mem.ArenaBufferOverhead]u8\n  pad := (16-(#cast(usize,&backing[0])&15))&15\n  arena := mem.arena_from_buffer(backing[pad..pad+mem.ArenaHeader+2])\n  _ = json.parse(arena, "\\"plain\\"")\n}\n')
    for mode in ('--debug', '--release'):
        output = work / 'out'
        subprocess.run([str(DYN), 'build', str(project), '--no-cache', '--quiet', '--output', str(output), mode], cwd=ROOT, check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=30)
        subprocess.run([str(DYN), 'build', str(capacity), '--no-cache', '--quiet', '--output', str(output), mode], cwd=ROOT, check=True, timeout=120)
        result = subprocess.run([str(output)], capture_output=True, timeout=30)
        assert result.returncode == 101 and b'arena exhausted' in result.stderr, (mode, 'fixed arena must panic')
print(f'PASS JSON owned keys/strings, UTF-8, escapes, surrogates, controls, error offsets and rollback: {len(valid)} valid/{len(invalid)} invalid (debug/release)')
