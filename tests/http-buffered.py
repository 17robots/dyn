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
fn commit(raw: rawptr, head: []const u8, size: usize) io.Transfer {
  sink := #cast(*Sink, raw)
  sink.commits += 1
  if sink.fail { return io.Transfer{ failure: io.Failure{ kind: io.Kind.System, native: sink.code } } }
  return io.Transfer{ transferred: #len(head) + size }
}
fn write(raw: rawptr, source: []const u8) io.Transfer {
  sink := #cast(*Sink, raw)
  sink.writes += 1
  return io.Transfer{ transferred: #len(source) }
}
fn response(sink: *Sink) http.Response {
  return http.Response{ output: io.Writer{ data: sink, write: write }, reserve_body: reserve, commit_body: commit }
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
  if !io.failed(http.respond_buffered(&r, 9, http.ResponseOptions{}).failure) { #panic("length") }
  if !io.failed(http.respond_buffered(&r, 1, http.ResponseOptions{ content_type: "bad\r\n" }).failure) { #panic("header injection") }
  huge: [9000]u8
  for i in 0..#len(huge) { huge[i] = 'a' }
  if http.respond_buffered(&r, 1, http.ResponseOptions{ reason: huge[..] }).failure.kind != io.Kind.Capacity { #panic("head capacity") }
  if sink.commits != 0 || r.started { #panic("published invalid head") }
  if io.failed(http.respond_buffered(&r, 1, http.ResponseOptions{}).failure) || !r.finished || sink.commits != 1 || sink.writes != 0 { #panic("commit") }
  if !io.failed(http.respond_buffered(&r, 1, http.ResponseOptions{}).failure) || sink.commits != 1 { #panic("recommit") }
  for native in [0, -73] {
    failing := Sink{ fail: true, code: #cast(isize, native) }
    failed := response(&failing)
    _ = http.body_buffer(&failed, 1)
    first := http.respond_buffered(&failed, 0, http.ResponseOptions{})
    if first.failure.kind != io.Kind.System || first.failure.native != #cast(isize, native) { #panic("native failure") }
    buffered_replay := http.respond_buffered(&failed, 0, http.ResponseOptions{})
    if buffered_replay.failure.kind != first.failure.kind || buffered_replay.failure.native != first.failure.native { #panic("buffered sticky replay") }
    replay := http.respond(&failed, "retry", http.ResponseOptions{})
    if replay.failure.kind != first.failure.kind || replay.failure.native != first.failure.native || failing.commits != 1 || failing.writes != 0 { #panic("sticky error") }
  }
  fallback := response(&sink)
  _ = http.body_buffer(&fallback, 8)
  if io.failed(http.respond(&fallback, "fallback", http.ResponseOptions{}).failure) || #len(fallback.reserved) != 0 { #panic("cancel reservation") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-http-buffered-') as tmp:
    project=Path(tmp);(project/'main.dyn').write_text(SOURCE)
    for release in [False,True]:
        binary=project/'app'
        subprocess.run([str(DYN),'build',str(project),'--no-cache','--quiet','--output',str(binary)]+(['--release'] if release else []),check=True)
        subprocess.run([str(binary)],check=True,timeout=10)
print('PASS buffered HTTP validation, publication, fallback and sticky native errors (debug/release)')
