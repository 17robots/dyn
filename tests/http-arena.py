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
use io "std/io"
use http "std/net/http"
use bytes "std/bytes"
use mem "std/mem"
use parse "std/parse"
struct Oracle { expected: []const u8, at: usize }
fn oracle_write(raw: rawptr, data: []const u8) usize!io.IoErr {
  oracle := #cast(*Oracle, raw)
  if data.len > oracle.expected.len - oracle.at { #panic("extra request bytes") }
  if !bytes.equal(data, oracle.expected[oracle.at..oracle.at + data.len]) { #panic("request wire") }
  oracle.at += data.len
  return data.len
}
fn request_check(body: []const u8, expected: []const u8) {
  arena := mem.arena_alloc(0)
  feed := Feed{ data: "HTTP/1.1 204 No Content\r\n\r\n", step: 1 }
  oracle := Oracle{ expected: expected }
  _ = http.client_do(arena, io.Reader{ data: &feed, read: read_feed }, io.Writer{ data: &oracle, write: oracle_write }, "POST", "?x", "host", body) catch { #panic("large request") }
  if oracle.at != expected.len { #panic("large request") }
  mem.arena_release(arena)
}
fn error_read(raw: rawptr, data: []u8) usize!io.IoErr {
  _ = raw
  _ = data
  fail .PermissionDenied
}
fn error_write(raw: rawptr, data: []const u8) usize!io.IoErr {
  _ = raw
  _ = data
  fail .PermissionDenied
}
fn denied(err: io.IoErr) bool {
  case err {
    .PermissionDenied => { return true }
    _ => { return false }
  }
}
fn invalid(err: io.IoErr) bool {
  case err {
    .InvalidInput => { return true }
    _ => { return false }
  }
}
fn io_check(write_failure: bool) {
  arena := mem.arena_alloc(0)
  _ = mem.push_bytes(arena, 7)
  mark := mem.arena_mark(arena)
  writer := io.Writer{ write: sink }
  if write_failure { writer.write = error_write }
  defer mem.arena_release(arena)
  _ = http.client_do(arena, io.Reader{ read: error_read }, writer, "GET", "/", "host", "") catch err {
    if !denied(err) || mem.arena_mark(arena) != mark { #panic("I/O rollback") }
    return
  }
  #panic("I/O failure lost")
}
struct Feed { data: []const u8, at: usize, cut: usize, step: usize }
fn read_feed(raw: rawptr, destination: []u8) usize!io.IoErr {
  feed := #cast(*Feed, raw)
  count := feed.data.len - feed.at
  if feed.at < feed.cut && count > feed.cut - feed.at { count = feed.cut - feed.at }
  if count > feed.step { count = feed.step }
  if count > destination.len { count = destination.len }
  for i in 0..count { destination[i] = feed.data[feed.at + i] }
  feed.at += count
  return count
}
fn sink(raw: rawptr, data: []const u8) usize!io.IoErr {
  _ = raw
  return data.len
}
fn check(wire: []const u8, expected: []const u8, valid: bool, method: []const u8, capacity: usize) {
  splits := wire.len + 1
  if splits > 256 { splits = 2 }
  for cut in 0..splits {
    for step in [1, 7, 65536] {
      feed := Feed{ data: wire, cut: cut, step: #cast(usize, step) }
      arena := mem.arena_alloc(0)
      defer mem.arena_release(arena)
      _ = mem.push_bytes(arena, 3)
      mark := mem.arena_mark(arena)
      _ = capacity
      got := http.client_do(arena, io.Reader{ data: #cast(rawptr, &feed), read: read_feed }, io.Writer{ write: sink }, method, "/", "host", "") catch err {
        if valid { #panic("response validity") }
        if !invalid(err) { #panic("response error") }
        if mem.arena_mark(arena) != mark { #panic("response rollback") }
        continue
      }
      if !valid { #panic("response validity") }
      if !bytes.equal(got.body, expected) { #panic("response body") }
    }
  }
}
fn prefixes(first: []const u8, forced: []const u8) {
  for byte in first { if byte!=71 { #panic("chain first prefix") } }
  for byte in forced { if byte!=82 { #panic("chain later prefix") } }
}
fn chain_check(wire: []const u8, expected: []const u8, valid: bool) {
  for block in [160,176] {
    for step in [1,7,65536] {
      arena := mem.arena_alloc(#cast(usize,block))
      first := mem.push_bytes(arena,16)
      for *byte in first { byte.*=71 }
      forced := mem.push_bytes(arena,33)
      for *byte in forced { byte.*=82 }
      mark := mem.arena_mark(arena)
      if arena.current.previous!=arena { #panic("prior forced chain") }
      current := arena.current
      feed := Feed{data:wire,step:#cast(usize,step)}
      got := http.client_do(arena, io.Reader{data:&feed,read:read_feed},io.Writer{write:sink},"GET","/","host","") catch err {
        if valid { #panic("chain response validity") }
        if !invalid(err) || mem.arena_mark(arena)!=mark || arena.current!=current { #panic("chain failure rollback") }
        prefixes(first, forced)
        mem.arena_release(arena)
        continue
      }
      if !valid { #panic("chain response validity") }
      {
        if !bytes.equal(got.body,expected) || got.status!=200 { #panic("chain response body") }
        checksum:usize=0
        for byte in got.raw { checksum+=#cast(usize,byte) }
        // An independent allocation must not reclaim or overwrite the result.
        tail := mem.push_bytes(arena,4096)
        for *byte in tail { byte.*=99 }
        after:usize=0
        for byte in got.raw { after+=#cast(usize,byte) }
        if !bytes.equal(got.body,expected) || got.raw.len<expected.len || after!=checksum { #panic("chain retained response") }
      }
      prefixes(first, forced)
      mem.arena_release(arena)
    }
  }
}
fn decode_check(wire: []const u8, expected: []const u8, valid: bool, offset: usize) {
  arena := mem.arena_alloc(0)
  defer mem.arena_release(arena)
  _ = mem.push_bytes(arena, 5)
  mark := mem.arena_mark(arena)
  got := http.decode_chunked(arena, wire) catch err {
    if valid { #panic("decode validity") }
    if parse.offset(err) != offset || mem.arena_mark(arena) != mark { #panic("decode rollback") }
    return
  }
  if !valid { #panic("decode validity") }
  if !bytes.equal(got.value, expected) { #panic("decode bytes") }
}
fn live_alias_check() {
  arena := mem.arena_alloc(0)
  wire: []const u8 = "3\r\nabc\r\n0\r\n\r\nrest"
  borrowed := mem.push_bytes(arena, wire.len)
  _ = mem.copy(borrowed, wire)
  got := http.decode_chunked(arena, borrowed) catch { #panic("live decode alias") }
  if got.consumed != 13 || got.value.len != 3 || !bytes.equal(got.value, "abc") || !bytes.equal(borrowed, wire) { #panic("live decode alias") }
  method := mem.push_bytes(arena, 4)
  _ = mem.copy(method, "HEAD")
  feed := Feed{ data: "HTTP/1.1 200 OK\r\nContent-Length: 999999\r\n\r\n", step: 1 }
  result := http.client_do(arena, io.Reader{ data: &feed, read: read_feed }, io.Writer{ write: sink }, method, "/", "host", "") catch { #panic("live method alias") }
  if result.body.len != 0 || !bytes.equal(method, "HEAD") { #panic("live method alias") }
  mem.arena_release(arena)
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
chain_cases = [
    ('HTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\nabcdef', 'abcdef', True),
    ('HTTP/1.1 200 OK\r\n\r\nclose body', 'close body', True),
    (chunk, 'abcde', True),
    ('HTTP/1.1 100 Continue\r\n\r\n' + chunk, 'abcde', True),
    ('HTTP/1.1 100 Continue\r\n\r\nHTTP/1.1 200 OK\r\nContent-Length: 6\r\n\r\nabcdef', 'abcdef', True),
    ('HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\nshort', '', False),
    (chunk_head + '1\r\naXX', '', False),
]
for wire, body, valid in chain_cases:
    SOURCE += f'  chain_check({q(wire)}, {q(body)}, {str(valid).lower()})\n'
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
    ('decode overlap', 'storage: [256 + mem.ArenaBufferOverhead]u8\narena := mem.arena_from_buffer(storage[..])\n_ = http.decode_chunked(arena, arena.data[mem.ArenaHeader + 80..mem.ArenaHeader + 90]) catch { return }'),
    ('client late argument overlap', 'storage: [256 + mem.ArenaBufferOverhead]u8\narena := mem.arena_from_buffer(storage[..])\n_ = http.client_do(arena, io.Reader{ read: error_read }, io.Writer{ write: sink }, "GET", "/", "host", arena.data[mem.ArenaHeader + 80..mem.ArenaHeader + 90]) catch { return }'),
    ('decode exhaustion', 'storage: [2 + mem.ArenaBufferOverhead]u8\narena := mem.arena_from_buffer(storage[..])\narena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader + 2])\n_ = http.decode_chunked(arena, "3\\r\\nabc\\r\\n0\\r\\n\\r\\n") catch { return }'),
    ('client exhaustion', 'storage: [128 + mem.ArenaBufferOverhead]u8\narena := mem.arena_from_buffer(storage[..])\narena = mem.arena_from_buffer(arena.data[..mem.ArenaHeader + 128])\nfeed := Feed{ data: "HTTP/1.1 200 OK\\r\\nContent-Length: 100\\r\\n\\r\\nxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx", step: 1 }\n_ = http.client_do(arena, io.Reader{ data: &feed, read: read_feed }, io.Writer{ write: sink }, "GET", "/", "host", "") catch { return }'),
]
with tempfile.TemporaryDirectory(prefix='dyn-http-arena-panic-') as temporary:
    project = Path(temporary)
    prefix = SOURCE[:SOURCE.index('fn main() {')]
    for mode in ([], ['--release']):
        for name, statement in PANICS:
            (project / 'main.dyn').write_text(prefix + 'fn main() { ' + statement + ' }\n')
            binary = project / 'panic'
            subprocess.run([str(DYN), 'build', str(project), '--quiet', '--no-cache', '--output', str(binary), *mode], env=ENV, check=True, timeout=120)
            got = subprocess.run([str(binary)], env=ENV, capture_output=True, timeout=10)
            expected = b'overlaps arena output' if 'overlap' in name else b'arena exhausted'
            assert got.returncode != 0 and expected in got.stderr, (name, mode, got.returncode, got.stderr)
print('PASS HTTP arena: large wire oracles, tiny chained blocks, interim/final framing, retained results/prefixes, exact rollback, aliases, native-zero I/O, exhaustion panics')
