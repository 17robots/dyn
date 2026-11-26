#!/usr/bin/env python3
"""Buffered I/O and INI stop after the first failure, including empty calls."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE = r'''use "std/fail"
use "std/io"
use "std/bufio"
use "std/encoding/ini"
struct Sink { calls: usize }
// A destination that takes one byte, then fails.
fn fail_write(data: rawptr, source: []const u8) usize!io.IoErr {
  status: fail.Status
  count := fail_write_status(data, &status, source)
  try io.check_status(&status)
  return count
}
fn fail_write_status(data: rawptr, status: *fail.Status, source: []const u8) usize {
  state := #cast(*Sink, data)
  state.calls += 1
  failure := fail.make(fail.Kind.PermissionDenied, "write", "sink", "")
  failure.native = -13
  fail.set(status, failure)
  return 1
}
fn fail_read(data: rawptr, destination: []u8) usize!io.IoErr {
  status: fail.Status
  count := fail_read_status(data, &status, destination)
  try io.check_status(&status)
  return count
}
fn fail_read_status(data: rawptr, status: *fail.Status, destination: []u8) usize {
  state := #cast(*Sink, data)
  state.calls += 1
  destination[0] = 'x'
  failure := fail.make(fail.Kind.PermissionDenied, "read", "source", "")
  failure.native = -13
  fail.set(status, failure)
  return 1
}
fn ini_failed(scan: *ini.Scanner) bool {
  _ = ini.next(scan) catch { return true }
  return false
}
fn main() {
  // A failed status makes every later buffered call do nothing.
  sink: Sink
  storage: [8]u8
  status: fail.Status
  writer := bufio.writer(io.Writer{ data: &sink, write: fail_write }, storage[..0])
  io.write_status(&status, bufio.writer_adapter(&writer), "abc")
  io.write_status(&status, bufio.writer_adapter(&writer), "abc")
  bufio.writer_flush(&status, &writer)
  if !status.failed || status.failure.kind != fail.Kind.PermissionDenied || sink.calls != 1 { #panic("writer failure") }
  // Buffered bytes stay buffered after a failed flush, for a fresh status to retry.
  writes: Sink
  staged := bufio.writer(io.Writer{ data: &writes, write: fail_write }, storage[..])
  staging: fail.Status
  io.write_status(&staging, bufio.writer_adapter(&staged), "abcdef")
  if staging.failed || staged.used != 6 || writes.calls != 0 { #panic("staged write") }
  bufio.writer_flush(&staging, &staged)
  if !staging.failed || staged.used != 6 || writes.calls != 1 { #panic("failed flush keeps bytes") }
  for capacity in [0, 8] {
    reads: Sink
    reading: fail.Status
    reader := bufio.reader(io.Reader{ data: &reads, read: fail_read }, storage[..#cast(usize, capacity)])
    output: [4]u8
    _ = io.read_status(&reading, bufio.reader_adapter(&reader), output[..])
    _ = bufio.read_line(&reading, &reader)
    until := bufio.read_until(&reading, &reader, output[..], 10)
    if !reading.failed || reading.failure.kind != fail.Kind.PermissionDenied || reads.calls != 1 { #panic("reader failure") }
    if !reader.ended || until.status != bufio.ReadStatus.End { #panic("records end after a failure") }
  }
  scan := ini.scanner("bad\nx=1")
  first := ini_failed(&scan)
  first_ended := scan.ended
  offset := scan.offset
  // The scanner stays failed: the next call fails the same way and reads nothing.
  again := ini_failed(&scan)
  if !first || !again || !first_ended || !scan.ended || scan.error_line != 1 || scan.offset != offset { #panic("ini sticky failure") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-std-sticky-') as directory:
    work=Path(directory)
    (work/'main.dyn').write_text(SOURCE)
    for mode in ('debug','release'):
        subprocess.run([DYN,'build',str(work),'--'+mode,'--quiet','--no-cache','--output',str(work/'test')],check=True,timeout=120)
        result=subprocess.run([str(work/'test')],capture_output=True,timeout=10)
        assert result.returncode==0,(result.stdout,result.stderr)
        print('PASS buffered I/O and INI sticky errors '+mode,flush=True)
