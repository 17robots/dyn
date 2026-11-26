#!/usr/bin/env python3
"""Buffered I/O passes a stream's failure back and keeps unflushed bytes; an INI
scanner stays failed after its first failure."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE = r'''use "std/io"
use "std/bufio"
use "std/encoding/ini"
struct Sink { calls: usize }
// A destination that fails every write.
fn fail_write(data: rawptr, source: []const u8) usize!io.IoErr {
  state := #cast(*Sink, data)
  state.calls += 1
  fail .PermissionDenied
}
// A source that fails every read.
fn fail_read(data: rawptr, destination: []u8) usize!io.IoErr {
  state := #cast(*Sink, data)
  state.calls += 1
  fail .PermissionDenied
}
fn denied(err: io.IoErr) bool {
  case err {
    .PermissionDenied => { return true }
    _ => { return false }
  }
}
fn write_err(writer: *bufio.Writer, text: []const u8) io.IoErr {
  io.write(bufio.writer_adapter(writer), text) catch err { return err }
  #panic("write should fail")
}
fn flush_err(writer: *bufio.Writer) io.IoErr {
  bufio.writer_flush(writer) catch err { return err }
  #panic("flush should fail")
}
fn read_err(reader: *bufio.Reader, output: []u8) io.IoErr {
  _ = io.read(bufio.reader_adapter(reader), output) catch err { return err }
  #panic("read should fail")
}
fn line_err(reader: *bufio.Reader) io.IoErr {
  _ = bufio.read_line(reader) catch err { return err }
  #panic("read_line should fail")
}
fn ini_failed(scan: *ini.Scanner) bool {
  _ = ini.next(scan) catch { return true }
  return false
}
fn main() {
  // Unbuffered, a write passes the destination's failure straight back.
  sink: Sink
  storage: [8]u8
  writer := bufio.writer(io.Writer{ data: &sink, write: fail_write }, storage[..0])
  if !denied(write_err(&writer, "abc")) || sink.calls != 1 { #panic("writer failure") }
  // Buffered bytes stay buffered after a failed flush, for a retry.
  writes: Sink
  staged := bufio.writer(io.Writer{ data: &writes, write: fail_write }, storage[..])
  io.write(bufio.writer_adapter(&staged), "abcdef") catch { #panic("staged write") }
  if staged.used != 6 || writes.calls != 0 { #panic("staged write") }
  if !denied(flush_err(&staged)) || staged.used != 6 || writes.calls != 1 { #panic("failed flush keeps bytes") }
  for capacity in [0, 8] {
    reads: Sink
    reader := bufio.reader(io.Reader{ data: &reads, read: fail_read }, storage[..#cast(usize, capacity)])
    output: [4]u8
    if !denied(read_err(&reader, output[..])) || reads.calls != 1 { #panic("reader failure") }
  }
  lines: Sink
  line_reader := bufio.reader(io.Reader{ data: &lines, read: fail_read }, storage[..])
  if !denied(line_err(&line_reader)) || lines.calls != 1 { #panic("read_line failure") }
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
        print('PASS buffered I/O failures and INI sticky errors '+mode,flush=True)
