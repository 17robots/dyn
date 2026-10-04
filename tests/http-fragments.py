#!/usr/bin/env python3
"""HTTP framing survives every transport split and byte-at-a-time delivery."""
import json
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
struct Feed { data: []const u8, at: usize, cut: usize, step: usize }
fn read_feed(raw: rawptr, destination: []u8) io.Result {
  feed := #cast(*Feed) raw
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
      feed := Feed{ data: wire, cut: cut, step: #cast(usize) step }
      request: [256]u8 = [] response: [65536]u8 = []
      got := http.client_do(io.Reader{ data: #cast(rawptr) &feed, read: &read_feed }, io.Writer{ write: &sink }, request[..], response[..capacity], method, "/", "host", "")
      if got.ok != valid { #panic("response validity") }
      if valid && !bytes.equal(got.body, expected) { #panic("response body") }
      if !valid && got.error != http.ErrorKind.Invalid { #panic("response error") }
    }
  }
}
fn server_check(wire: []const u8) {
  for cut in 0..#len(wire) + 1 {
    for step in [1, 7, 65536] {
      feed := Feed{ data: wire, cut: cut, step: #cast(usize) step }
      storage: [65536]u8 = []
      state := http.server(io.Reader{ data: #cast(rawptr) &feed, read: &read_feed }, io.Writer{ write: &sink }, storage[..])
      first := http.receive(&state)
      if !first.ok || !bytes.equal(first.request.body, "abc") || !bytes.equal(first.request.target, "/one") { #panic("first request") }
      second := http.receive(&state)
      if !second.ok || !bytes.equal(second.request.body, "") || !bytes.equal(second.request.target, "/two") { #panic("second request") }
      last := http.receive(&state)
      if last.ok || last.error != http.ErrorKind.End { #panic("request eof") }
    }
  }
}
fn server_invalid(wire: []const u8) {
  feed := Feed{ data: wire, step: 1 }
  storage: [256]u8 = []
  state := http.server(io.Reader{ data: #cast(rawptr) &feed, read: &read_feed }, io.Writer{ write: &sink }, storage[..])
  got := http.receive(&state)
  if got.ok || got.error != http.ErrorKind.Invalid { #panic("invalid request") }
}
fn main() {
'''
q = json.dumps
chunk_head = 'HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n'
chunk = chunk_head + '3;foo=bar\r\nabc\r\n2\r\nde\r\n0\r\nX-Trailer: yes\r\n\r\n'
cases = [
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
for bad in ['g\r\n', ';x\r\n', '10000000000000000\r\n', '1\r\naXX', '0\r\nMissingColon\r\n\r\n', '0\r\nContent-Length: 1\r\n\r\n', '0\r\nTransfer-Encoding: chunked\r\n\r\n']:
    cases.append((chunk_head + bad, '', False, 'GET', 65536))
# Truncation anywhere in encoded framing or payload must never report success.
for end in range(len(chunk_head), len(chunk)):
    cases.append((chunk[:end], '', False, 'GET', 65536))
for wire, body, valid, method, capacity in cases:
    SOURCE += f'  check({q(wire)}, {q(body)}, {str(valid).lower()}, {q(method)}, {capacity})\n'
for malformed in ['bad\r\n\r\n', 'POST / HTTP/1.1\r\nContent-Length: 3\r\n\r\na', 'POST / HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n0\r\n\r\n']:
    SOURCE += '  server_invalid(' + q(malformed) + ')\n'
SOURCE += '  server_check(' + q('POST /one HTTP/1.1\r\nContent-Length: 3\r\n\r\nabcGET /two HTTP/1.1\r\n\r\n') + ')\n}\n'
with tempfile.TemporaryDirectory(prefix='dyn-http-fragments-') as temporary:
    project = Path(temporary)
    (project / 'main.dyn').write_text(SOURCE)
    for mode in ([], ['--release']):
        binary = project / 'http-fragments'
        subprocess.run([str(DYN), 'build', str(project), '--quiet', '--no-cache', '--output', str(binary), *mode], env=ENV, check=True, timeout=120)
        subprocess.run([str(binary)], env=ENV, check=True, timeout=30)
print('PASS HTTP fragments: byte reads, every split, interim responses, trailers, invalid/truncated framing, pipelining')
