#!/usr/bin/env python3
"""Arena HTTP producers: independent wire expectations and bounded split delivery."""
import json
import re
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build' / 'dyn-release')).resolve()
ENV = dict(os.environ, DYN_SDK=str(ROOT))
SOURCE = r'''
use "std/io" io
use "std/net/http" http
use "std/bytes" bytes
use "std/mem" mem
use "std/errors" errors
struct Oracle { expected: []const u8, at: usize }
fn oracle_write(raw: rawptr, data: []const u8) io.Result {
  oracle := #cast(*Oracle, raw)
  if #len(data) > #len(oracle.expected) - oracle.at { #panic("extra request bytes") }
  if !bytes.equal(data, oracle.expected[oracle.at..oracle.at + #len(data)]) { #panic("request wire") }
  oracle.at += #len(data)
  return io.Result{ transferred: #len(data), status: io.Status.Complete }
}
fn request_check(body: []const u8, expected: []const u8) {
  arena := mem.Arena{}
  feed := Feed{ data: "HTTP/1.1 204 No Content\r\n\r\n", step: 1 }
  oracle := Oracle{ expected: expected }
  got := http.client_do(&arena, io.Reader{ data: &feed, read: read_feed }, io.Writer{ data: &oracle, write: oracle_write }, "POST", "?x", "host", body)
  if !got.ok || oracle.at != #len(expected) { #panic("large request") }
  mem.arena_release(&arena)
}
fn error_read(raw: rawptr, data: []u8) io.Result {
  _ = raw
  _ = data
  return io.Result{ kind: errors.Kind.PermissionDenied, error: 0, status: io.Status.Error }
}
fn error_write(raw: rawptr, data: []const u8) io.Result {
  _ = raw
  _ = data
  return io.Result{ kind: errors.Kind.PermissionDenied, error: 0, status: io.Status.Error }
}
fn io_check(write_failure: bool) {
  arena := mem.Arena{}
  _ = mem.push_bytes_uninit(&arena, 7)
  mark := mem.arena_mark(&arena)
  writer := io.Writer{ write: sink }
  if write_failure { writer.write = error_write }
  got := http.client_do(&arena, io.Reader{ read: error_read }, writer, "GET", "/", "host", "")
  if got.ok || got.kind != errors.Kind.PermissionDenied || got.error != 0 || got.detail != http.ErrorKind.Io || #len(got.raw) != 0 || #len(got.body) != 0 || mem.arena_mark(&arena) != mark { #panic("I/O rollback") }
  mem.arena_release(&arena)
}
struct Feed { data: []const u8, at: usize, cut: usize, step: usize }
fn read_feed(raw: rawptr, destination: []u8) io.Result {
  feed := #cast(*Feed, raw)
  count := #len(feed.data) - feed.at
  if feed.at < feed.cut && count > feed.cut - feed.at { count = feed.cut - feed.at }
  if count > feed.step { count = feed.step }
  if count > #len(destination) { count = #len(destination) }
  for i in 0..count { destination[i] = feed.data[feed.at + i] }
  feed.at += count
  if feed.at == #len(feed.data) { return io.Result{ transferred: count, status: io.Status.End } }
  return io.Result{ transferred: count, status: io.Status.Complete }
}
fn sink(raw: rawptr, data: []const u8) io.Result {
  _ = raw
  return io.Result{ transferred: #len(data), status: io.Status.Complete }
}
fn check(wire: []const u8, expected: []const u8, valid: bool, method: []const u8, capacity: usize) {
  splits := #len(wire) + 1
  if splits > 256 { splits = 2 }
  for cut in 0..splits {
    for step in [1, 7, 65536] {
      feed := Feed{ data: wire, cut: cut, step: #cast(usize, step) }
      arena := mem.Arena{}
      _ = mem.push_bytes_uninit(&arena, 3)
      mark := mem.arena_mark(&arena)
      _ = capacity
      got := http.client_do(&arena, io.Reader{ data: #cast(rawptr, &feed), read: read_feed }, io.Writer{ write: sink }, method, "/", "host", "")
      if got.ok != valid { #panic("response validity") }
      if valid && !bytes.equal(got.body, expected) { #panic("response body") }
      if !valid && got.detail != http.ErrorKind.Invalid { #panic("response error") }
      if !valid && (#len(got.raw) != 0 || #len(got.body) != 0 || mem.arena_mark(&arena) != mark) { #panic("response rollback") }
      mem.arena_release(&arena)
    }
  }
}
fn decode_check(wire: []const u8, expected: []const u8, valid: bool, offset: usize) {
  arena := mem.Arena{}
  _ = mem.push_bytes_uninit(&arena, 5)
  mark := mem.arena_mark(&arena)
  got := http.decode_chunked(&arena, wire)
  if got.ok != valid { #panic("decode validity") }
  if valid && (!bytes.equal(got.value, expected) || got.count != #len(expected)) { #panic("decode bytes") }
  if !valid && (#len(got.value) != 0 || got.offset != offset || got.error != 0 || mem.arena_mark(&arena) != mark) { #panic("decode rollback") }
  mem.arena_release(&arena)
}
fn live_alias_check() {
  arena := mem.Arena{}
  wire: []const u8 = "3\r\nabc\r\n0\r\n\r\nrest"
  borrowed := mem.push_bytes_uninit(&arena, #len(wire))
  _ = mem.copy(borrowed, wire)
  got := http.decode_chunked(&arena, borrowed)
  if !got.ok || got.consumed != 13 || got.count != 3 || !bytes.equal(got.value, "abc") || !bytes.equal(borrowed, wire) { #panic("live decode alias") }
  method := mem.push_bytes_uninit(&arena, 4)
  _ = mem.copy(method, "HEAD")
  feed := Feed{ data: "HTTP/1.1 200 OK\r\nContent-Length: 999999\r\n\r\n", step: 1 }
  result := http.client_do(&arena, io.Reader{ data: &feed, read: read_feed }, io.Writer{ write: sink }, method, "/", "host", "")
  if !result.ok || #len(result.body) != 0 || !bytes.equal(method, "HEAD") { #panic("live method alias") }
  mem.arena_release(&arena)
}
fn main() {
  live_alias_check()
  io_check(false)
  io_check(true)
  decode_check("3\r\nabc\r\n0\r\nX: yes\r\n\r\nextra", "abc", true, 0)
  decode_check("1\r\naX\n0\r\n\r\n", "", false, 4)
  decode_check("1\r\na\r\n0\r\n", "", false, 9)
'''
def q(text):
    # Dyn uses byte escapes, not JSON's Unicode/backspace/form-feed escapes.
    encoded = json.dumps(text).replace('\\b', '\\x08').replace('\\f', '\\x0c')
    return re.sub(r'\\u00([0-9a-fA-F]{2})', lambda m: '\\x' + m.group(1), encoded)
# Trailer field values follow ordinary HTTP controls: HTAB is allowed; other
# C0 controls and DEL are not. The malformed byte is at chunk-wire offset 7.
for control in [byte for byte in range(32) if byte != 9] + [127]:
    wire = '0\r\nX: a' + chr(control) + 'b\r\n\r\n'
    SOURCE += '  decode_check(' + q(wire) + ', "", false, 7)\n'
SOURCE += '  decode_check(' + q('0\r\nX: a\tb\r\n\r\n') + ', "", true, 0)\n'
large_body = 'r' * 70000
SOURCE += '  request_check(' + q(large_body) + ', ' + q('POST /?x HTTP/1.1\r\nHost: host\r\nConnection: close\r\nContent-Length: 70000\r\n\r\n' + large_body) + ')\n'

chunk_head = 'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n'
chunk = chunk_head + '3;foo=bar\r\nabc\r\n2\r\nde\r\n0\r\nX-Trailer: yes\r\n\r\n'
cases = [
    (chunk_head + '11170\r\n' + 'c' * 70000 + '\r\n0\r\nT: ok\r\n\r\n', 'c' * 70000, True, 'GET', 0),
    ('HTTP/1.1 304 Not Modified\r\nContent-Length: 9000\r\n\r\n', '', True, 'GET', 0),
    ('HTTP/1.1 101 Switching Protocols\r\n\r\nopaque', '', True, 'GET', 0),
    ('HTTP/1.1 200 OK\r\nContent-Length: 70000\r\n\r\n' + 'z' * 70000, 'z' * 70000, True, 'GET', 0),
    ('HTTP/1.1 200 OK\r\nX-Large: ' + 'a' * 16384 + '\r\nContent-Length: 3\r\n\r\nabc', 'abc', True, 'GET', 65536),
    (chunk_head + '1\r\na\r\n' * 4096 + '0\r\n\r\n', 'a' * 4096, True, 'GET', 65536),
    (chunk, 'abcde', True, 'GET', 65536),
    ('HTTP/1.1 100 Continue\r\n\r\n' + chunk, 'abcde', True, 'GET', 65536),
    ('HTTP/1.1 200 OK\r\nContent-Length: 3\r\n\r\nabc', 'abc', True, 'GET', 65536),
    ('HTTP/1.1 200 OK\r\nContent-Length: 9999\r\n\r\n', '', True, 'HEAD', 65536),
    ('HTTP/1.1 200 OK\r\n\r\nclose body', 'close body', True, 'GET', 29),
    ('HTTP/1.1 204 No Content\r\n\r\n', '', True, 'GET', 65536),
    ('HTTP/1.1 200 OK\r\n\r\n', '', True, 'CONNECT', 65536),
]
for bad in ['g\r\n', ';x\r\n', '10000000000000000\r\n', '1\r\naXX', '0\r\nMissingColon\r\n\r\n', '0\r\nContent-Length: 1\r\n\r\n', '0\r\nTransfer-Encoding: chunked\r\n\r\n', '0\r\nX: a\x00b\r\n\r\n', '0\r\nX: a\nb\r\n\r\n', '0\r\nX: a\x7fb\r\n\r\n']:
    cases.append((chunk_head + bad, '', False, 'GET', 65536))
# Truncation anywhere in encoded framing or payload must never report success.
for end in range(len(chunk_head), len(chunk)):
    cases.append((chunk[:end], '', False, 'GET', 65536))
for wire, body, valid, method, capacity in cases:
    SOURCE += f'  check({q(wire)}, {q(body)}, {str(valid).lower()}, {q(method)}, {capacity})\n'
SOURCE += '}\n'
with tempfile.TemporaryDirectory(prefix='dyn-http-fragments-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    for mode in ([], ['--release']):
        binary = project / 'http-fragments'
        subprocess.run([str(DYN), 'build', str(project), '--quiet', '--no-cache', '--output', str(binary), *mode], env=ENV, check=True, timeout=120)
        subprocess.run([str(binary)], env=ENV, check=True, timeout=30)
PANICS = [
    ('decode overlap', 'storage: [256]u8 = []\narena := mem.arena_from_buffer(storage[..])\n_ = http.decode_chunked(&arena, storage[80..90])'),
    ('client late argument overlap', 'storage: [256]u8 = []\narena := mem.arena_from_buffer(storage[..])\n_ = http.client_do(&arena, io.Reader{ read: error_read }, io.Writer{ write: sink }, "GET", "/", "host", storage[80..90])'),
    ('decode exhaustion', 'storage: [2]u8 = []\narena := mem.arena_from_buffer(storage[..])\n_ = http.decode_chunked(&arena, "3\\r\\nabc\\r\\n0\\r\\n\\r\\n")'),
    ('client exhaustion', 'storage: [128]u8 = []\narena := mem.arena_from_buffer(storage[..])\nfeed := Feed{ data: "HTTP/1.1 200 OK\\r\\nContent-Length: 100\\r\\n\\r\\nxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", step: 1 }\n_ = http.client_do(&arena, io.Reader{ data: &feed, read: read_feed }, io.Writer{ write: sink }, "GET", "/", "host", "")'),
]
with tempfile.TemporaryDirectory(prefix='dyn-http-arena-panic-') as temporary:
    project = Path(temporary)
    prefix = SOURCE[:SOURCE.index('fn main() {')]
    for name, statement in PANICS:
        (project / 'main.dyn').write_text(prefix + 'fn main() { ' + statement + ' }\n')
        binary = project / 'panic'
        subprocess.run([str(DYN), 'build', str(project), '--quiet', '--no-cache', '--output', str(binary)], env=ENV, check=True, timeout=120)
        got = subprocess.run([str(binary)], env=ENV, capture_output=True, timeout=10)
        assert got.returncode != 0 and b'panic' in got.stderr.lower(), (name, got.returncode, got.stderr)
print('PASS HTTP arena: large request/response wire oracles, byte reads/splits, framing/trailers, rollback, aliases, native-zero I/O, exhaustion panics')
