#!/usr/bin/env python3
"""Transport-owned response storage: validation, publication and sticky errors."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve()
SOURCE=r'''
use "std/io"
use "std/net/http"
struct Sink { body: [32]u8, reserves: usize, commits: usize, writes: usize, fail: bool, code: isize }
fn reserve(raw: rawptr, size: usize) []u8 {
  sink := #cast(*Sink, raw)
  sink.reserves += 1
  if size > 32 { return sink.body[..0] }
  return sink.body[..size]
}
fn commit(raw: rawptr, head: []const u8, size: usize) usize!io.IoErr {
  sink := #cast(*Sink, raw)
  sink.commits += 1
  if sink.fail { fail .System(sink.code) }
  return head.len + size
}
fn write(raw: rawptr, source: []const u8) usize!io.IoErr {
  sink := #cast(*Sink, raw)
  sink.writes += 1
  return source.len
}
fn response(sink: *Sink) http.Response {
  return http.Response{ output: io.Writer{ data: sink, write: write }, reserve_body: reserve, commit_body: commit }
}
fn buffered_err(r: *http.Response, length: usize, options: http.ResponseOptions) io.IoErr {
  http.respond_buffered(r, length, options) catch err { return err }
  #panic("respond_buffered unexpectedly succeeded")
}
fn invalid(err: io.IoErr) bool {
  case err {
    .InvalidInput => { return true }
    _ => { return false }
  }
}
fn capacity(err: io.IoErr) bool {
  case err {
    .Capacity => { return true }
    _ => { return false }
  }
}
fn system(err: io.IoErr, code: isize) bool {
  case err {
    .System(native) => { return native == code }
    _ => { return false }
  }
}
fn main() {
  plain := http.Response{}
  if http.body_buffer(&plain, 8).len != 0 { #panic("unsupported backend") }
  sink := Sink{}
  r := response(&sink)
  if http.body_buffer(&r, 33).len != 0 { #panic("capacity") }
  storage := http.body_buffer(&r, 8)
  if storage.len != 8 { #panic("reserve") }
  storage[0] = 'x'
  if http.body_buffer(&r, 8).len != 0 || sink.reserves != 2 { #panic("repeat reserve") }
  if !invalid(buffered_err(&r, 9, http.ResponseOptions{})) { #panic("length") }
  if !invalid(buffered_err(&r, 1, http.ResponseOptions{ content_type: "bad\r\n" })) { #panic("header injection") }
  huge: [9000]u8
  for i in 0..huge.len { huge[i] = 'a' }
  if !capacity(buffered_err(&r, 1, http.ResponseOptions{ reason: huge[..] })) { #panic("head capacity") }
  if sink.commits != 0 || r.started { #panic("published invalid head") }
  http.respond_buffered(&r, 1, http.ResponseOptions{}) catch { #panic("commit") }
  if !r.finished || sink.commits != 1 || sink.writes != 0 { #panic("commit") }
  if !invalid(buffered_err(&r, 1, http.ResponseOptions{})) || sink.commits != 1 { #panic("recommit") }
  for native in [0, -73] {
    failing := Sink{ fail: true, code: #cast(isize, native) }
    failed := response(&failing)
    _ = http.body_buffer(&failed, 1)
    if !system(buffered_err(&failed, 0, http.ResponseOptions{}), #cast(isize, native)) { #panic("native failure") }
    // The failed response is finished: nothing more is written.
    if !invalid(buffered_err(&failed, 0, http.ResponseOptions{})) { #panic("buffered replay") }
    refused := false
    http.respond(&failed, "retry", http.ResponseOptions{}) catch err { refused = invalid(err) }
    if !refused || failing.commits != 1 || failing.writes != 0 { #panic("finished after failure") }
  }
  fallback := response(&sink)
  _ = http.body_buffer(&fallback, 8)
  http.respond(&fallback, "fallback", http.ResponseOptions{}) catch { #panic("fallback") }
  if fallback.reserved.len != 0 { #panic("cancel reservation") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-http-buffered-') as tmp:
    project=Path(tmp);(project/'main.dyn').write_text(SOURCE)
    for release in [False,True]:
        binary=project/'app'
        subprocess.run([str(DYN),'build',str(project),'--no-cache','--quiet','--output',str(binary)]+(['--release'] if release else []),check=True)
        subprocess.run([str(binary)],check=True,timeout=10)
print('PASS buffered HTTP validation, publication, fallback and native failures (debug/release)')
