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
use "std/fail"
use "std/io" io
use "std/bytes" bytes
struct Probe { calls: usize, code: isize, mode: usize }
fn check(ok: bool) { if !ok { #panic("CSV/XML diagnostic contract") } }
fn refused(status: *fail.Status, code: isize) usize {
  failure := fail.make(fail.Kind.PermissionDenied, "probe", "", "denied")
  failure.native = code
  fail.set(status, failure)
  return 0
}
fn read(data: rawptr, status: *fail.Status, destination: []u8) usize {
  p := #cast(*Probe, data)
  p.calls += 1
  // A stream ends with a read that returns 0, so mode 1 (one byte, then the
  // end) is read twice; every other mode is read once.
  check(p.calls == 1 || (p.mode == 1 && p.calls == 2))
  if p.mode == 2 || p.calls == 2 { return 0 }
  if p.mode == 1 {
    destination[0] = 'x'
    return 1
  }
  return refused(status, p.code)
}
fn write(data: rawptr, status: *fail.Status, source: []const u8) usize {
  p := #cast(*Probe, data)
  p.calls += 1
  check(p.calls == 1)
  return refused(status, p.code)
}
struct CsvField { value: csv.Field, failure: fail.Failure }
fn csv_next(state: *csv.Scanner, destination: []u8) CsvField {
  status: fail.Status
  value := csv.next(&status, state, destination)
  return CsvField{ value: value, failure: status.failure }
}
fn csv_stream(state: *csv.StreamScanner, destination: []u8) CsvField {
  status: fail.Status
  value := csv.next_stream(&status, state, destination)
  return CsvField{ value: value, failure: status.failure }
}
struct XmlEvent { value: xml.Next, failure: fail.Failure }
fn xml_next(state: *xml.Scanner) XmlEvent {
  status: fail.Status
  value := xml.next(&status, state)
  return XmlEvent{ value: value, failure: status.failure }
}
fn xml_stream(state: *xml.StreamScanner) XmlEvent {
  status: fail.Status
  value := xml.next_stream(&status, state)
  return XmlEvent{ value: value, failure: status.failure }
}
fn callback_contracts() {
  scratch: [32]u8
  for code in 0..2 {
    p := Probe{ code: 0 - #cast(isize, code * 13) }
    reader := io.Reader{ data: #cast(rawptr, &p), read: read }
    sink := io.Writer{ data: #cast(rawptr, &p), write: write }
    c := csv.stream_scanner(reader)
    f := csv_stream(&c, scratch[..])
    check(!f.value.found && f.failure.kind == fail.Kind.PermissionDenied && f.failure.native == p.code)
    p.code = -99
    again := csv_stream(&c, scratch[..])
    check(!again.value.found && p.calls == 1)
    p.code = 0 - #cast(isize, code * 13)
    p.calls = 0
    x := xml.stream_scanner(reader, scratch[..])
    r := xml_stream(&x)
    check(!r.value.found && r.failure.kind == fail.Kind.PermissionDenied && r.failure.native == p.code)
    p.code = -99
    r2 := xml_stream(&x)
    check(!r2.value.found && p.calls == 1)
    p.code = 0 - #cast(isize, code * 13)
    p.calls = 0
    // A failed write leaves the status failed; later writes do nothing.
    writing: fail.Status
    cw := csv.writer(sink)
    csv.write_field(&writing, &cw, "x", false)
    check(writing.failed)
    saved := p.code
    p.code = -99
    csv.write_field(&writing, &cw, "", true)
    csv.write_field(&writing, &cw, "later", false)
    check(p.calls == 1 && writing.failure.kind == fail.Kind.PermissionDenied && writing.failure.native == saved)
    p.code = saved
    p.calls = 0
    xml_writing: fail.Status
    xw := xml.writer(sink)
    xml.write_text(&xml_writing, &xw, "x")
    check(xml_writing.failed)
    p.code = -99
    xml.write_text(&xml_writing, &xw, "")
    xml.write_start(&xml_writing, &xw, "")
    xml.write_attribute(&xml_writing, &xw, "", "")
    xml.write_end(&xml_writing, &xw, "")
    xml.write_start_end(&xml_writing, &xw, true)
    xml.write_start_end(&xml_writing, &xw, false)
    check(p.calls == 1 && xml_writing.failure.kind == fail.Kind.PermissionDenied && xml_writing.failure.native == saved)
  }
  eof := Probe{ mode: 1 }
  c := csv.stream_scanner(io.Reader{ data: #cast(rawptr, &eof), read: read })
  f := csv_stream(&c, scratch[..])
  check(f.value.found && #len(f.value.text) == 1 && f.value.end_input && f.failure.kind == fail.Kind.Ok)
  check(!csv_stream(&c, scratch[..]).value.found && eof.calls == 2)
  eof.calls = 0
  x := xml.stream_scanner(io.Reader{ data: #cast(rawptr, &eof), read: read }, scratch[..])
  xe := xml_stream(&x)
  check(xe.value.found && xe.failure.kind == fail.Kind.Ok && bytes.equal(xe.value.value.text, "x"))
  check(!xml_stream(&x).value.found && eof.calls == 2)
  bad := csv.scanner("a,b\"c")
  check(csv_next(&bad, scratch[..]).value.found)
  cf := csv_next(&bad, scratch[..])
  check(!cf.value.found && cf.failure.kind == fail.Kind.InvalidInput && cf.failure.offset == 2)
  short := csv.scanner("abc")
  cap := csv_next(&short, scratch[..0])
  check(!cap.value.found && cap.failure.kind == fail.Kind.Capacity)
  xb := xml.scanner("<a")
  xr := xml_next(&xb)
  check(!xr.value.found && xr.failure.kind == fail.Kind.InvalidInput && xr.failure.offset == 2)
  check(!xml_next(&xb).value.found)
  attr := xml.attributes(xml.Event{ attributes: " a=bad" })
  attributing: fail.Status
  ar := xml.next_attribute(&attributing, &attr)
  check(!ar.found && attributing.failure.kind == fail.Kind.InvalidInput)
  p := Probe{}
  w := xml.writer(io.Writer{ data: #cast(rawptr, &p), write: write })
  invalid_name: fail.Status
  xml.write_start(&invalid_name, &w, "")
  xml.write_text(&invalid_name, &w, "later")
  check(invalid_name.failure.kind == fail.Kind.InvalidInput && p.calls == 0)
}

fn additional_contracts() {
  scratch: [32]u8
  // Complete with no bytes is also EOF, and must never trigger another read.
  p := Probe{mode: 2}
  reader := io.Reader{data: #cast(rawptr, &p), read: read}
  c := csv.stream_scanner(reader)
  f := csv_stream(&c, scratch[..0])
  check(f.value.found && #len(f.value.text) == 0 && f.value.end_input && f.value.end_record && f.failure.kind == fail.Kind.Ok)
  check(!csv_stream(&c, scratch[..0]).value.found && p.calls == 1)
  p.calls = 0
  x := xml.stream_scanner(reader, scratch[..])
  r := xml_stream(&x)
  check(!r.value.found && r.failure.kind == fail.Kind.Ok)
  check(!xml_stream(&x).value.found && p.calls == 1)
  // A zero-sized XML buffer reports capacity before any callback.
  p.calls = 0
  xs := xml.stream_scanner(reader, scratch[..0])
  cap := xml_stream(&xs)
  check(!cap.value.found && cap.failure.kind == fail.Kind.Capacity)
  check(!xml_stream(&xs).value.found && p.calls == 0)
  empty := xml.scanner("")
  end := xml_next(&empty)
  check(!end.value.found && end.failure.kind == fail.Kind.Ok)
  attrs := xml.attributes(xml.Event{})
  none: fail.Status
  check(!xml.next_attribute(&none, &attrs).found && !none.failed)
  zero_field: csv.Field
  zero_next: xml.Next
  zero_attribute: xml.Attribute
  check(!zero_field.found && !zero_next.found && !zero_attribute.found)
  // CSV diagnostics retain the field's starting byte offset.
  bad := csv.scanner("a,\"unfinished")
  check(csv_next(&bad, scratch[..]).value.found)
  failure := csv_next(&bad, scratch[..])
  check(!failure.value.found && failure.failure.kind == fail.Kind.InvalidInput && failure.failure.offset == 2)
  check(!csv_next(&bad, scratch[..0]).value.found)
  // XML diagnostics use byte offsets, including an incomplete UTF-8 name.
  partial: [3]u8 = ['<', 226, 130]
  xb := xml.scanner(partial[..])
  xr := xml_next(&xb)
  check(!xr.value.found && xr.failure.kind == fail.Kind.InvalidInput && xr.failure.offset == 1)
  eof := xml.scanner("<a x='")
  er := xml_next(&eof)
  check(!er.value.found && er.failure.kind == fail.Kind.InvalidInput && er.failure.offset == 6)
  invalid: [1]u8 = [255]
  writing: fail.Status
  w := xml.writer(io.Writer{data: #cast(rawptr, &p), write: write})
  xml.write_text(&writing, &w, invalid[..])
  check(writing.failure.kind == fail.Kind.InvalidInput)
  xml.write_text(&writing, &w, "")
  xml.write_attribute(&writing, &w, "a", "")
  xml.write_end(&writing, &w, "a")
  xml.write_start_end(&writing, &w, false)
  check(p.calls == 0)
  // Empty writes succeed without touching the sink.
  clean: fail.Status
  clean_csv := csv.writer(io.Writer{data: #cast(rawptr, &p), write: write})
  clean_xml := xml.writer(io.Writer{data: #cast(rawptr, &p), write: write})
  csv.write_field(&clean, &clean_csv, "", false)
  xml.write_text(&clean, &clean_xml, "")
  check(!clean.failed && p.calls == 0)
  // Zero writers reject real output.
  zwc: csv.Writer
  zwx: xml.Writer
  zero_csv: fail.Status
  csv.write_field(&zero_csv, &zwc, "x", false)
  check(zero_csv.failure.kind == fail.Kind.InvalidState && zero_csv.failure.native == 0)
  zero_xml: fail.Status
  xml.write_text(&zero_xml, &zwx, "x")
  check(zero_xml.failure.kind == fail.Kind.InvalidState && zero_xml.failure.native == 0)
  stack: [4][]const u8
  check(xml.valid("<a/>", stack[..]) && !xml.valid("<a x=bad/>", stack[..]) && !xml.valid("<a>&unknown;</a>", stack[..]))
}

struct Chunk { calls: usize, source: []const u8, at: usize, split: usize, limit: usize }
fn read_chunk(data: rawptr, status: *fail.Status, destination: []u8) usize {
  state := #cast(*Chunk, data)
  state.calls += 1
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
  return take
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
      a: [32]u8
      b: [32]u8
      first := csv_next(&direct, a[..capacity])
      second := csv_stream(&streamed, b[..capacity])
      if first.failure.kind != second.failure.kind || first.value.found != second.value.found || (capacity == 4 && first.value.found != expected) {
        #panic("CSV scanner acceptance mismatch")
      }
      if !second.value.found {
        calls := chunk.calls
        repeated := csv_stream(&streamed, b[..0])
        check(!repeated.value.found && chunk.calls == calls)
      }
      if first.value.found && (!bytes.equal(first.value.text, second.value.text) || first.value.end_record != second.value.end_record) {
        #panic("CSV field mismatch")
      }
    }
  }
}
fn xml_check(source: []const u8, expected: bool) {
  direct := xml.scanner(source)
  original := xml_next(&direct)
  if original.value.found != expected {
    #panic("XML fixture invalid")
  }
  if expected {
    for capacity in 0..#len(source) {
      chunk := Chunk{source: source, limit: 1}
      storage: [128]u8
      streamed := xml.stream_scanner(input(&chunk), storage[..capacity])
      event := xml_stream(&streamed)
      if event.value.found || event.failure.kind != fail.Kind.Capacity {
        #panic("XML short storage")
      }
    }
  }
  for limit in 0..4 {
    for split in 1..#len(source) + 1 {
      chunk := Chunk{source: source, split: split, limit: limit}
      storage: [128]u8
      capacity := #len(source)
      if !expected {
        capacity += 1
      }
      streamed := xml.stream_scanner(input(&chunk), storage[..capacity])
      event := xml_stream(&streamed)
      if event.failure.kind != original.failure.kind || event.value.found != original.value.found {
        #panic("XML chunk acceptance mismatch")
      }
      if !event.value.found {
        calls := chunk.calls
        repeated := xml_stream(&streamed)
        check(!repeated.value.found && chunk.calls == calls)
      }
      if event.value.found && (event.value.value.kind != original.value.value.kind || !bytes.equal(event.value.value.name, original.value.value.name) || !bytes.equal(event.value.value.text, original.value.value.text) || !bytes.equal(event.value.value.attributes, original.value.value.attributes)) {
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
