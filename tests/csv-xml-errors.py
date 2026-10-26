#!/usr/bin/env python3
"""CSV/XML public diagnostics, sticky callback failures, EOF and fragmentation.

Standalone regression: generated fixtures have no dependency on retained audits.
DYN overrides the compiler executable; both debug and release runs are bounded.
"""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get("DYN", ROOT / "build/dyn-release")).resolve()

SOURCE = r'''use "std/encoding/csv" csv
use "std/encoding/xml" xml
use "std/io" io
use "std/errors" errors
use "std/bytes" bytes
struct Probe { calls: usize, code: isize, mode: usize }
fn check(ok: bool) { if !ok { #panic("CSV/XML diagnostic contract") } }
fn read(data: rawptr, destination: []u8) io.Result {
  p := #cast(*Probe, data)
  p.calls += 1
  check(p.calls == 1)
  if p.mode == 2 { return io.Result{} }
  if p.mode == 1 { destination[0] = 'x'
  return io.Result{ transferred: 1, status: io.Status.End } }
  return io.Result{ status: io.Status.Error, kind: errors.Kind.PermissionDenied, error: p.code }
}
fn write(data: rawptr, source: []const u8) io.Result {
  p := #cast(*Probe, data)
  p.calls += 1
  check(p.calls == 1)
  return io.Result{ status: io.Status.Error, kind: errors.Kind.PermissionDenied, error: p.code }
}
fn callback_contracts() {
  scratch: [32]u8 = []
  for code in 0..2 {
    p := Probe{ code: 0 - #cast(isize, code * 13) }
    reader := io.Reader{ data: #cast(rawptr, &p), read: read }
    sink := io.Writer{ data: #cast(rawptr, &p), write: write }
    c := csv.stream_scanner(reader)
    f := csv.next_stream(&c, scratch[..])
    check(!f.ok && f.kind == errors.Kind.PermissionDenied && f.error == p.code && f.detail == csv.ErrorKind.Io)
    p.code = -99
    again := csv.next_stream(&c, scratch[..])
    check(!again.ok && again.kind == f.kind && again.error == f.error && p.calls == 1 && c.kind == f.kind && c.system_error == f.error && c.error == csv.ErrorKind.Io && again.detail == f.detail)
    p.code = 0 - #cast(isize, code * 13)
    p.calls = 0
    x := xml.stream_scanner(reader, scratch[..])
    r := xml.next_stream(&x)
    check(!r.ok && r.kind == errors.Kind.PermissionDenied && r.error == p.code && r.detail == xml.ErrorKind.Io)
    p.code = -99
    r2 := xml.next_stream(&x)
    check(!r2.ok && r2.kind == r.kind && r2.error == r.error && p.calls == 1 && x.kind == r.kind && x.system_error == r.error && x.error == xml.ErrorKind.Io && r2.detail == r.detail)
    p.code = 0 - #cast(isize, code * 13)
    p.calls = 0
    cw := csv.writer(sink)
    check(!csv.write_field(&cw, "x", false))
    saved := p.code
    p.code = -99
    check(!csv.write_field(&cw, "", true) && !csv.write_field(&cw, "later", false) && p.calls == 1 && cw.kind == errors.Kind.PermissionDenied && cw.error == saved && cw.detail == csv.ErrorKind.Io)
    p.code = saved
    p.calls = 0
    xw := xml.writer(sink)
    check(!xml.write_text(&xw, "x"))
    p.code = -99
    check(!xml.write_text(&xw, "") && !xml.write_start(&xw, "") && !xml.write_attribute(&xw, "", "") && !xml.write_end(&xw, "") && !xml.write_start_end(&xw, true) && !xml.write_start_end(&xw, false) && p.calls == 1)
    check(xw.kind == errors.Kind.PermissionDenied && xw.error == saved && xw.detail == xml.ErrorKind.Io)
  }
  eof := Probe{ mode: 1 }
  c := csv.stream_scanner(io.Reader{ data: #cast(rawptr, &eof), read: read })
  f := csv.next_stream(&c, scratch[..])
  check(f.ok && #len(f.text) == 1 && f.end_input && f.kind == errors.Kind.None && f.error == 0)
  check(!csv.next_stream(&c, scratch[..]).ok && eof.calls == 1)
  eof.calls = 0
  x := xml.stream_scanner(io.Reader{ data: #cast(rawptr, &eof), read: read }, scratch[..])
  xe := xml.next_stream(&x)
  check(xe.ok && xe.kind == errors.Kind.None && xe.error == 0 && xe.detail == xml.ErrorKind.None && bytes.equal(xe.value.text, "x"))
  check(!xml.next_stream(&x).ok && eof.calls == 1)
  bad := csv.scanner("a,b\"c")
  check(csv.next(&bad, scratch[..]).ok)
  cf := csv.next(&bad, scratch[..])
  check(!cf.ok && cf.kind == errors.Kind.InvalidInput && cf.error == 0 && cf.detail == csv.ErrorKind.Syntax && bad.error_offset == 2)
  short := csv.scanner("abc")
  cap := csv.next(&short, scratch[..0])
  check(!cap.ok && cap.kind == errors.Kind.Capacity && cap.error == 0 && cap.detail == csv.ErrorKind.Capacity)
  xb := xml.scanner("<a")
  xr := xml.next(&xb)
  check(!xr.ok && xr.kind == errors.Kind.InvalidInput && xr.error == 0 && xr.detail == xml.ErrorKind.Syntax && xb.error_offset == 2)
  check(xml.next(&xb).kind == xr.kind)
  attr := xml.attributes(xml.Event{ attributes: " a=bad" })
  ar := xml.next_attribute(&attr)
  check(!ar.ok && ar.kind == errors.Kind.InvalidInput && ar.error == 0 && ar.detail == xml.ErrorKind.Syntax)
  check(xml.next_attribute(&attr).kind == ar.kind)
  p := Probe{}
  w := xml.writer(io.Writer{ data: #cast(rawptr, &p), write: write })
  check(!xml.write_start(&w, "") && w.failed && w.kind == errors.Kind.InvalidInput && w.error == 0 && w.detail == xml.ErrorKind.Syntax)
  check(!xml.write_text(&w, "later") && p.calls == 0)
}

fn additional_contracts() {
  scratch: [32]u8 = []
  // Complete with no bytes is also EOF, and must never trigger another read.
  p := Probe{mode: 2}
  reader := io.Reader{data: #cast(rawptr, &p), read: read}
  c := csv.stream_scanner(reader)
  f := csv.next_stream(&c, scratch[..0])
  check(f.ok && #len(f.text) == 0 && f.end_input && f.end_record && f.kind == errors.Kind.None && f.error == 0 && f.detail == csv.ErrorKind.None)
  check(!csv.next_stream(&c, scratch[..0]).ok && p.calls == 1 && c.error == csv.ErrorKind.None)
  p.calls = 0
  x := xml.stream_scanner(reader, scratch[..])
  r := xml.next_stream(&x)
  check(!r.ok && r.kind == errors.Kind.None && r.error == 0 && r.detail == xml.ErrorKind.None)
  check(!xml.next_stream(&x).ok && p.calls == 1 && x.error == xml.ErrorKind.None)
  // A zero-sized XML buffer reports capacity before any callback.
  p.calls = 0
  xs := xml.stream_scanner(reader, scratch[..0])
  cap := xml.next_stream(&xs)
  check(!cap.ok && cap.kind == errors.Kind.Capacity && cap.error == 0 && cap.detail == xml.ErrorKind.Capacity)
  check(!xml.next_stream(&xs).ok && p.calls == 0 && xs.kind == cap.kind && xs.error == cap.detail && xs.system_error == 0)
  empty := xml.scanner("")
  end := xml.next(&empty)
  check(!end.ok && end.kind == errors.Kind.None && end.error == 0 && end.detail == xml.ErrorKind.None)
  attrs := xml.attributes(xml.Event{})
  attr := xml.next_attribute(&attrs)
  check(!attr.ok && attr.kind == errors.Kind.None && attr.error == 0 && attr.detail == xml.ErrorKind.None)
  zero_field: csv.Field
  zero_result: xml.Result
  zero_attribute: xml.Attribute
  check(!zero_field.ok && zero_field.kind == errors.Kind.None && zero_field.error == 0 && zero_field.detail == csv.ErrorKind.None)
  check(!zero_result.ok && zero_result.kind == errors.Kind.None && zero_result.error == 0 && zero_result.detail == xml.ErrorKind.None)
  check(!zero_attribute.ok && zero_attribute.kind == errors.Kind.None && zero_attribute.error == 0 && zero_attribute.detail == xml.ErrorKind.None)
  // CSV diagnostics retain the field's starting byte offset.
  bad := csv.scanner("a,\"unfinished")
  check(csv.next(&bad, scratch[..]).ok)
  failure := csv.next(&bad, scratch[..])
  check(!failure.ok && failure.kind == errors.Kind.InvalidInput && failure.error == 0 && failure.detail == csv.ErrorKind.Syntax && bad.error_offset == 2)
  check(csv.next(&bad, scratch[..0]).detail == failure.detail && bad.error_offset == 2)
  // XML diagnostics use byte offsets, including an incomplete UTF-8 name.
  partial: [3]u8 = ['<', 226, 130]
  xb := xml.scanner(partial[..])
  xr := xml.next(&xb)
  check(!xr.ok && xr.kind == errors.Kind.InvalidInput && xr.error == 0 && xr.detail == xml.ErrorKind.Syntax && xb.error_offset == 1)
  eof := xml.scanner("<a x='")
  er := xml.next(&eof)
  check(!er.ok && er.error == 0 && er.kind == errors.Kind.InvalidInput && er.detail == xml.ErrorKind.Syntax && eof.error_offset == 6)
  invalid: [1]u8 = [255]
  w := xml.writer(io.Writer{data: #cast(rawptr, &p), write: write})
  check(!xml.write_text(&w, invalid[..]) && w.failed && w.kind == errors.Kind.InvalidInput && w.error == 0 && w.detail == xml.ErrorKind.Syntax)
  check(!xml.write_text(&w, "") && !xml.write_attribute(&w, "a", "") && !xml.write_end(&w, "a") && !xml.write_start_end(&w, false) && p.calls == 0)
  // Empty writes succeed before failure without touching the sink.
  clean_csv := csv.writer(io.Writer{data: #cast(rawptr, &p), write: write})
  clean_xml := xml.writer(io.Writer{data: #cast(rawptr, &p), write: write})
  check(csv.write_field(&clean_csv, "", false) && xml.write_text(&clean_xml, "") && p.calls == 0)
  check(clean_csv.kind == errors.Kind.None && clean_csv.error == 0 && clean_csv.detail == csv.ErrorKind.None)
  check(clean_xml.kind == errors.Kind.None && clean_xml.error == 0 && clean_xml.detail == xml.ErrorKind.None)
  // Zero writers reject real output, then also reject empty output.
  zwc: csv.Writer
  zwx: xml.Writer
  check(!csv.write_field(&zwc, "x", false) && zwc.kind == errors.Kind.InvalidInput && zwc.error == -22 && zwc.detail == csv.ErrorKind.Io)
  check(!csv.write_field(&zwc, "", false) && zwc.error == -22 && zwc.kind == errors.Kind.InvalidInput)
  check(!xml.write_text(&zwx, "x") && zwx.kind == errors.Kind.InvalidInput && zwx.error == -22 && zwx.detail == xml.ErrorKind.Io)
  check(!xml.write_text(&zwx, "") && !xml.write_start(&zwx, "") && zwx.error == -22 && zwx.detail == xml.ErrorKind.Io)
  stack: [4][]const u8
  check(xml.valid("<a/>", stack[..]) && !xml.valid("<a x=bad/>", stack[..]) && !xml.valid("<a>&unknown;</a>", stack[..]))
}

struct Chunk { calls: usize, source: []const u8, at: usize, split: usize, limit: usize }
fn read_chunk(data: rawptr, destination: []u8) io.Result {
  state := #cast(*Chunk, data)
  state.calls += 1
  if state.at == #len(state.source) {
    return io.Result{ status: io.Status.End }
  }
  take := #len(state.source) - state.at
  if state.at < state.split && take > state.split - state.at {
    take = state.split - state.at
  }
  if state.limit > 0 && take > state.limit {
    take = state.limit
  }
  if take > #len(destination) {
    take = #len(destination)
  }
  for i in 0..take {
    destination[i] = state.source[state.at + i]
  }
  state.at += take
  return io.Result{ transferred: take }
}
fn input(state: *Chunk) io.Reader {
  return io.Reader{ data: #cast(rawptr, state), read: read_chunk }
}
fn csv_check(source: []const u8, expected: bool) {
  for limit in 1..4 {
    for capacity in 0..5 {
      chunk := Chunk{source: source, limit: limit}
      streamed := csv.stream_scanner(input(&chunk))
      direct := csv.scanner(source)
      a: [32]u8 = []
      b: [32]u8 = []
      first := csv.next(&direct, a[..capacity])
      second := csv.next_stream(&streamed, b[..capacity])
      if first.kind != second.kind || first.error != 0 || second.error != 0 || first.detail != direct.error || second.detail != streamed.error || first.ok != second.ok || (capacity == 4 && first.ok != expected) || direct.error != streamed.error {
        #panic("CSV scanner acceptance mismatch")
      }
      if !second.ok {
        calls := chunk.calls
        repeated := csv.next_stream(&streamed, b[..0])
        check(!repeated.ok && repeated.kind == second.kind && repeated.error == second.error && repeated.detail == second.detail && chunk.calls == calls)
      }
      if first.ok && (!bytes.equal(first.text, second.text) || first.end_record != second.end_record) {
        #panic("CSV field mismatch")
      }
    }
  }
}
fn xml_check(source: []const u8, expected: bool) {
  direct := xml.scanner(source)
  original := xml.next(&direct)
  if original.ok != expected {
    #panic("XML fixture invalid")
  }
  if expected {
    for capacity in 0..#len(source) {
      chunk := Chunk{source: source, limit: 1}
      storage: [128]u8 = []
      streamed := xml.stream_scanner(input(&chunk), storage[..capacity])
      event := xml.next_stream(&streamed)
      if event.ok || event.kind != errors.Kind.Capacity || event.error != 0 || event.detail != xml.ErrorKind.Capacity || streamed.kind != event.kind || streamed.error != xml.ErrorKind.Capacity {
        #panic("XML short storage")
      }
    }
  }
  for limit in 0..4 {
    for split in 1..#len(source) + 1 {
      chunk := Chunk{source: source, split: split, limit: limit}
      storage: [128]u8 = []
      capacity := #len(source)
      if !expected {
        capacity += 1
      }
      streamed := xml.stream_scanner(input(&chunk), storage[..capacity])
      event := xml.next_stream(&streamed)
      if event.kind != original.kind || event.error != 0 || original.error != 0 || event.detail != streamed.error || original.detail != direct.error || event.ok != original.ok || streamed.error != direct.error {
        #panic("XML chunk acceptance mismatch")
      }
      if !event.ok {
        calls := chunk.calls
        repeated := xml.next_stream(&streamed)
        check(!repeated.ok && repeated.kind == event.kind && repeated.error == event.error && repeated.detail == event.detail && chunk.calls == calls)
      }
      if event.ok && (event.value.kind != original.value.kind || !bytes.equal(event.value.name, original.value.name) || !bytes.equal(event.value.text, original.value.text) || !bytes.equal(event.value.attributes, original.value.attributes)) {
        #panic("XML chunk contents mismatch")
      }
    }
  }
}

fn main() {
  callback_contracts()
  additional_contracts()
  for value in 0..256 {
    source: [4]u8 = ['"', 'a', '"', 0]
    source[3] = #cast(u8, value)
    expected := value == 44 || value == 10 || value == 13
    csv_check(source[..], expected)
  }
  csv_check("\"a\"", true)
  csv_check("\"a\"\"b\"", true)
  xml_check("<?pi x > y?>", true)
  xml_check("<?pi x > y > z?>", true)
  xml_check("<?pi x > y?", false)
  xml_check("<?pi x='>'?>", true)
  xml_check("<a x='>'/>", true)
  xml_check("<!-- > -->", true)
  xml_check("<![CDATA[ > ]]>", true)
}

'''


def main():
    env = dict(os.environ, DYN_SDK=str(ROOT))
    with tempfile.TemporaryDirectory(prefix="dyn-csv-xml-errors-") as temporary:
        project = Path(temporary) / "contracts"
        project.mkdir()
        (project / "main.dyn").write_text(SOURCE)
        for mode in ("--debug", "--release"):
            output = Path(temporary) / ("program.exe" if os.name == "nt" else "program")
            subprocess.run(
                [str(DYN), "build", str(project), "--no-cache", "--quiet",
                 "--output", str(output), mode],
                cwd=ROOT, env=env, check=True, timeout=90,
            )
            subprocess.run([str(output)], check=True, timeout=15)
    print("PASS CSV/XML diagnostics, callbacks, sticky failures, EOF, validation and fragmentation (debug/release)")


if __name__ == "__main__":
    main()
