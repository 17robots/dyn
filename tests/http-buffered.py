#!/usr/bin/env python3
"""Transport-owned response storage: validation, publication and sticky errors."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve()
SOURCE=r'''
use "std/fail"
use "std/io"
use "std/net/http"
struct Sink { body: [32]u8, reserves: usize, commits: usize, writes: usize, fail: bool, code: isize }
fn reserve(raw: rawptr, size: usize) []u8 {
  sink := #cast(*Sink, raw)
  sink.reserves += 1
  if size > 32 { return sink.body[..0] }
  return sink.body[..size]
}
fn commit(raw: rawptr, status: *fail.Status, head: []const u8, size: usize) usize {
  sink := #cast(*Sink, raw)
  sink.commits += 1
  if sink.fail {
    failure := fail.make(fail.Kind.System, "commit", "", "sink failure")
    failure.native = sink.code
    fail.set(status, failure)
    return 0
  }
  return #len(head) + size
}
fn write(raw: rawptr, status: *fail.Status, source: []const u8) usize {
  sink := #cast(*Sink, raw)
  sink.writes += 1
  return #len(source)
}
fn response(sink: *Sink) http.Response {
  return http.Response{ output: io.Writer{ data: sink, write: write }, reserve_body: reserve, commit_body: commit }
}
// Whether a respond_buffered with these arguments fails, with kind.
fn rejected(r: *http.Response, length: usize, options: http.ResponseOptions, kind: fail.Kind) bool {
  status: fail.Status
  http.respond_buffered(&status, r, length, options)
  return status.failed && status.failure.kind == kind
}
fn main() {
  plain := http.Response{}
  if #len(http.body_buffer(&plain, 8)) != 0 { #panic("unsupported backend") }
  sink := Sink{}
  r := response(&sink)
  if #len(http.body_buffer(&r, 33)) != 0 { #panic("capacity") }
  storage := http.body_buffer(&r, 8)
  if #len(storage) != 8 { #panic("reserve") }
  storage[0] = 'x'
  if #len(http.body_buffer(&r, 8)) != 0 || sink.reserves != 2 { #panic("repeat reserve") }
  if !rejected(&r, 9, http.ResponseOptions{}, fail.Kind.InvalidInput) { #panic("length") }
  if !rejected(&r, 1, http.ResponseOptions{ content_type: "bad\r\n" }, fail.Kind.InvalidInput) { #panic("header injection") }
  huge: [9000]u8
  for i in 0..#len(huge) { huge[i] = 'a' }
  if !rejected(&r, 1, http.ResponseOptions{ reason: huge[..] }, fail.Kind.Capacity) { #panic("head capacity") }
  if sink.commits != 0 || r.started { #panic("published invalid head") }
  status: fail.Status
  http.respond_buffered(&status, &r, 1, http.ResponseOptions{})
  if status.failed || !r.finished || sink.commits != 1 || sink.writes != 0 { #panic("commit") }
  if !rejected(&r, 1, http.ResponseOptions{}, fail.Kind.InvalidInput) || sink.commits != 1 { #panic("recommit") }
  for native in [0, -73] {
    failing := Sink{ fail: true, code: #cast(isize, native) }
    failed := response(&failing)
    _ = http.body_buffer(&failed, 1)
    first: fail.Status
    http.respond_buffered(&first, &failed, 0, http.ResponseOptions{})
    if first.failure.kind != fail.Kind.System || first.failure.native != #cast(isize, native) { #panic("native failure") }
    // The failed response is finished: nothing more is written.
    if !rejected(&failed, 0, http.ResponseOptions{}, fail.Kind.InvalidInput) { #panic("buffered replay") }
    replay: fail.Status
    http.respond(&replay, &failed, "retry", http.ResponseOptions{})
    if replay.failure.kind != fail.Kind.InvalidState || failing.commits != 1 || failing.writes != 0 { #panic("finished after failure") }
  }
  fallback := response(&sink)
  _ = http.body_buffer(&fallback, 8)
  plain_status: fail.Status
  http.respond(&plain_status, &fallback, "fallback", http.ResponseOptions{})
  if plain_status.failed || #len(fallback.reserved) != 0 { #panic("cancel reservation") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-http-buffered-') as tmp:
    project=Path(tmp);(project/'main.dyn').write_text(SOURCE)
    for release in [False,True]:
        binary=project/'app'
        subprocess.run([str(DYN),'build',str(project),'--no-cache','--quiet','--output',str(binary)]+(['--release'] if release else []),check=True)
        subprocess.run([str(binary)],check=True,timeout=10)
print('PASS buffered HTTP validation, publication, fallback and native failures (debug/release)')
