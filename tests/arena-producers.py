#!/usr/bin/env python3
"""Rule 4: producers take the arena first, retry blocks of unknown size, and push nothing on failure."""
import gzip
import os
from pathlib import Path
import subprocess
import tempfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
PAYLOAD = bytes((i * 7 + i // 13) % 251 for i in range(20000))
RAW = zlib.compressobj(9, zlib.DEFLATED, -15)
DEFLATED = RAW.compress(PAYLOAD) + RAW.flush()
GZIPPED = gzip.compress(PAYLOAD, mtime=0)


def literal(data):
    return '"' + ''.join('\\x%02x' % b for b in data) + '"'


SOURCE = f'''use "std/mem" mem
use "std/strings" strings
use "std/fmt" fmt
use "std/encoding/base64" base64
use "std/encoding/json" json
use "std/compress/deflate" deflate
use "std/compress/gzip" gzip
use "std/path" path
fn check(ok: bool, message: []const u8) {{
  if !ok {{
    #panic(message)
  }}
}}
fn main() {{
  arena: mem.Arena
  check(strings.equal(strings.join(&arena, strings.split(&arena, "a,b,c", ","), "+"), "a+b+c"), "join split")
  check(strings.equal(strings.replace(&arena, "a-b-c", "-", "::"), "a::b::c"), "replace")
  check(strings.equal(fmt.i64_decimal(&arena, -42), "-42") && strings.equal(fmt.u64_base(&arena, 255, 16, false), "ff"), "fmt")
  digits: [3]u8 = []
  fixed := mem.arena_from_buffer(digits[..])
  check(strings.equal(fmt.u64_decimal(&fixed, 123), "123") && mem.arena_used(&fixed) == 3, "fixed storage")
  encoded := base64.encode(&arena, "hello")
  check(strings.equal(encoded, "aGVsbG8="), "base64 encode")
  before := mem.arena_used(&arena)
  check(!base64.decode(&arena, "a!==").ok && mem.arena_used(&arena) == before, "failed decode pushes nothing")
  check(strings.equal(base64.decode(&arena, encoded).value, "hello"), "base64 decode")
  doc := json.make_object(&arena)
  _ = json.add_member(doc, "name", json.make_string(&arena, "boss"))
  check(strings.equal(json.encode(&arena, doc), "{{\\"name\\":\\"boss\\"}}"), "json encode")
  mark := mem.arena_used(&arena)
  big := deflate.inflate(&arena, {literal(DEFLATED)})
  check(big.ok && #len(big.value) == {len(PAYLOAD)} && big.value[{len(PAYLOAD) - 1}] == {PAYLOAD[-1]}, "inflate grows")
  check(mem.arena_used(&arena) == mark + {len(PAYLOAD)}, "retries leave only the output")
  member := gzip.decompress(&arena, {literal(GZIPPED)})
  check(member.ok && #len(member.value) == {len(PAYLOAD)} && member.consumed == {len(GZIPPED)}, "gunzip")
  check(!deflate.inflate(&arena, "\\xff\\xff").ok, "corrupt inflate")
  joined := path.join(&arena, "a/b", "c")
  check(joined.ok && strings.equal(joined.value, "a/b/c"), "path join")
}}
'''
with tempfile.TemporaryDirectory(prefix='dyn-arena-producers-') as temporary:
    project = Path(temporary)
    source = project / 'main.dyn'
    output = project / ('program.exe' if os.name == 'nt' else 'program')
    source.write_text(SOURCE)
    for release in (False, True):
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output),
                        *(['--release'] if release else [])], check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=20)
    source.write_text('use "std/mem" mem\nuse "std/encoding/json" json\nfn main() {\n  storage: [8]u8 = []\n  arena := mem.arena_from_buffer(storage[..])\n  _ = json.write_string(&arena, "a long string that cannot fit")\n}\n')
    subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=120)
    result = subprocess.run([str(output)], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and 'arena exhausted' in result.stderr, result.stderr
print('PASS arena producers: one arena-first form, trial growth with rewinds, fixed storage, nothing pushed on failure (debug/release)')
