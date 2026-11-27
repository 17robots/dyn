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

SOURCE = r'''use csv "std/encoding/csv"
use xml "std/encoding/xml"
use parse "std/parse"
use io "std/io"
use bytes "std/bytes"
struct Probe { calls: usize, code: isize, mode: usize }
fn check(ok: bool) { if !ok { #panic("CSV/XML diagnostic contract") } }
// A failure as a comparable kind: 0 none, 1 malformed (Invalid or
// InvalidInput), 2 too large (TooLarge or Capacity), 3 PermissionDenied,
// 4 anything else; offset for a parse failure.
struct Failure { kind: u8, offset: usize }
fn of_parse(err: parse.ParseErr) Failure {
  case err {
    .Invalid(at) => { return Failure{ kind: 1, offset: at } }
    .TooLarge(at) => { return Failure{ kind: 2, offset: at } }
    .Unsupported(at) => { return Failure{ kind: 2, offset: at } }
  }
}
fn of_io(err: io.IoErr) Failure {
  case err {
    .InvalidInput => { return Failure{ kind: 1 } }
    .Capacity => { return Failure{ kind: 2 } }
    .PermissionDenied => { return Failure{ kind: 3 } }
    _ => { return Failure{ kind: 4 } }
  }
}
fn read(data: rawptr, destination: []u8) usize!io.IoErr {
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
  fail .PermissionDenied
}
fn write(data: rawptr, source: []const u8) usize!io.IoErr {
  p := #cast(*Probe, data)
  p.calls += 1
  check(p.calls == 1)
  fail .PermissionDenied
}
// The failure of a write; kind 0 when it worked.
fn csv_write(state: *csv.Writer, value: []const u8, end_record: bool) Failure {
  csv.write_field(state, value, end_record) catch err { return of_io(err) }
  return Failure{}
}
fn xml_text(state: *xml.Writer, value: []const u8) Failure {
  xml.write_text(state, value) catch err { return of_io(err) }
  return Failure{}
}
fn xml_start(state: *xml.Writer, name: []const u8) Failure {
  xml.write_start(state, name) catch err { return of_io(err) }
  return Failure{}
}
fn xml_attribute(state: *xml.Writer, name: []const u8, value: []const u8) Failure {
  xml.write_attribute(state, name, value) catch err { return of_io(err) }
  return Failure{}
}
fn xml_end(state: *xml.Writer, name: []const u8) Failure {
  xml.write_end(state, name) catch err { return of_io(err) }
  return Failure{}
}
fn xml_start_end(state: *xml.Writer, self_closing: bool) Failure {
  xml.write_start_end(state, self_closing) catch err { return of_io(err) }
  return Failure{}
}
fn attribute_failure(state: *xml.AttributeScanner) Failure {
  _ = xml.next_attribute(state) catch err { return of_parse(err) }
  return Failure{}
}
// A field or event with whether the call returned one (the scanner's ended,
// inverted) and the call's failure.
struct Got { text: []u8, end_record: bool, end_input: bool, found: bool }
struct CsvField { value: Got, failure: Failure }
fn csv_next(state: *csv.Scanner, destination: []u8) CsvField {
  value := csv.next(state, destination) catch err { return CsvField{ failure: of_parse(err) } }
  return CsvField{ value: Got{ text: value.text, end_record: value.end_record, end_input: value.end_input, found: !state.ended } }
}
fn csv_stream(state: *csv.StreamScanner, destination: []u8) CsvField {
  value := csv.next_stream(state, destination) catch err { return CsvField{ failure: of_io(err) } }
  return CsvField{ value: Got{ text: value.text, end_record: value.end_record, end_input: value.end_input, found: !state.ended } }
}
struct EventGot { value: xml.Event, found: bool }
struct XmlEvent { value: EventGot, failure: Failure }
fn xml_next(state: *xml.Scanner) XmlEvent {
  value := xml.next(state) catch err { return XmlEvent{ failure: of_parse(err) } }
  return XmlEvent{ value: EventGot{ value: value, found: !state.ended } }
}
fn xml_stream(state: *xml.StreamScanner) XmlEvent {
  value := xml.next_stream(state) catch err { return XmlEvent{ failure: of_io(err) } }
  return XmlEvent{ value: EventGot{ value: value, found: !state.ended } }
}
fn callback_contracts() {
  scratch: [32]u8
  for code in 0..2 {
    p := Probe{ code: 0 - #cast(isize, code * 13) }
    reader := io.Reader{ data: #cast(rawptr, &p), read: read }
    sink := io.Writer{ data: #cast(rawptr, &p), write: write }
    c := csv.stream_scanner(reader)
    f := csv_stream(&c, scratch[..])
    check(!f.value.found && f.failure.kind == 3)
    p.code = -99
    again := csv_stream(&c, scratch[..])
    check(!again.value.found && p.calls == 1)
    p.code = 0 - #cast(isize, code * 13)
    p.calls = 0
    x := xml.stream_scanner(reader, scratch[..])
    r := xml_stream(&x)
    check(!r.value.found && r.failure.kind == 3)
    p.code = -99
    r2 := xml_stream(&x)
    check(!r2.value.found && p.calls == 1)
    p.code = 0 - #cast(isize, code * 13)
    p.calls = 0
    // A failed write reports the sink's failure.
    cw := csv.writer(sink)
    check(csv_write(&cw, "x", false).kind == 3 && p.calls == 1)
    p.calls = 0
    xw := xml.writer(sink)
    check(xml_text(&xw, "x").kind == 3 && p.calls == 1)
  }
  eof := Probe{ mode: 1 }
  c := csv.stream_scanner(io.Reader{ data: #cast(rawptr, &eof), read: read })
  f := csv_stream(&c, scratch[..])
  check(f.value.found && f.value.text.len == 1 && f.value.end_input && f.failure.kind == 0)
  check(!csv_stream(&c, scratch[..]).value.found && eof.calls == 2)
  eof.calls = 0
  x := xml.stream_scanner(io.Reader{ data: #cast(rawptr, &eof), read: read }, scratch[..])
  xe := xml_stream(&x)
  check(xe.value.found && xe.failure.kind == 0 && bytes.equal(xe.value.value.text, "x"))
  check(!xml_stream(&x).value.found && eof.calls == 2)
  bad := csv.scanner("a,b\"c")
  check(csv_next(&bad, scratch[..]).value.found)
  cf := csv_next(&bad, scratch[..])
  check(!cf.value.found && cf.failure.kind == 1 && cf.failure.offset == 2)
  short := csv.scanner("abc")
  cap := csv_next(&short, scratch[..0])
  check(!cap.value.found && cap.failure.kind == 2)
  xb := xml.scanner("<a")
  xr := xml_next(&xb)
  check(!xr.value.found && xr.failure.kind == 1 && xr.failure.offset == 2)
  check(!xml_next(&xb).value.found)
  attr := xml.attributes(xml.Event{ attributes: " a=bad" })
  check(attribute_failure(&attr).kind == 1 && attr.ended)
  p := Probe{}
  w := xml.writer(io.Writer{ data: #cast(rawptr, &p), write: write })
  check(xml_start(&w, "").kind == 1 && p.calls == 0)
}

fn additional_contracts() {
  scratch: [32]u8
  // Complete with no bytes is also EOF, and must never trigger another read.
  p := Probe{mode: 2}
  reader := io.Reader{data: #cast(rawptr, &p), read: read}
  c := csv.stream_scanner(reader)
  f := csv_stream(&c, scratch[..0])
  check(f.value.found && f.value.text.len == 0 && f.value.end_input && f.value.end_record && f.failure.kind == 0)
  check(!csv_stream(&c, scratch[..0]).value.found && p.calls == 1)
  p.calls = 0
  x := xml.stream_scanner(reader, scratch[..])
  r := xml_stream(&x)
  check(!r.value.found && r.failure.kind == 0)
  check(!xml_stream(&x).value.found && p.calls == 1)
  // A zero-sized XML buffer reports capacity before any callback.
  p.calls = 0
  xs := xml.stream_scanner(reader, scratch[..0])
  cap := xml_stream(&xs)
  check(!cap.value.found && cap.failure.kind == 2)
  check(!xml_stream(&xs).value.found && p.calls == 0)
  empty := xml.scanner("")
  end := xml_next(&empty)
  check(!end.value.found && end.failure.kind == 0)
  attrs := xml.attributes(xml.Event{})
  check(attribute_failure(&attrs).kind == 0 && attrs.ended)
  zero_field: csv.Field
  zero_event: xml.Event
  zero_attribute: xml.Attribute
  check(zero_field.text.len == 0 && zero_event.name.len == 0 && zero_attribute.name.len == 0)
  // CSV diagnostics retain the field's starting byte offset.
  bad := csv.scanner("a,\"unfinished")
  check(csv_next(&bad, scratch[..]).value.found)
  failure := csv_next(&bad, scratch[..])
  check(!failure.value.found && failure.failure.kind == 1 && failure.failure.offset == 2)
  check(!csv_next(&bad, scratch[..0]).value.found)
  // XML diagnostics use byte offsets, including an incomplete UTF-8 name.
  partial: [3]u8 = ['<', 226, 130]
  xb := xml.scanner(partial[..])
  xr := xml_next(&xb)
  check(!xr.value.found && xr.failure.kind == 1 && xr.failure.offset == 1)
  eof := xml.scanner("<a x='")
  er := xml_next(&eof)
  check(!er.value.found && er.failure.kind == 1 && er.failure.offset == 6)
  invalid: [1]u8 = [255]
  w := xml.writer(io.Writer{data: #cast(rawptr, &p), write: write})
  // Text XML cannot carry fails before anything is written.
  check(xml_text(&w, invalid[..]).kind == 1 && p.calls == 0)
  // Empty writes succeed without touching the sink.
  clean_csv := csv.writer(io.Writer{data: #cast(rawptr, &p), write: write})
  clean_xml := xml.writer(io.Writer{data: #cast(rawptr, &p), write: write})
  check(csv_write(&clean_csv, "", false).kind == 0 && xml_text(&clean_xml, "").kind == 0 && p.calls == 0)
  // Zero writers reject real output.
  zwc: csv.Writer
  zwx: xml.Writer
  check(csv_write(&zwc, "x", false).kind == 1)
  check(xml_text(&zwx, "x").kind == 1)
  stack: [4][]const u8
  check(xml.valid("<a/>", stack[..]) && !xml.valid("<a x=bad/>", stack[..]) && !xml.valid("<a>&unknown;</a>", stack[..]))
}

struct Chunk { calls: usize, source: []const u8, at: usize, split: usize, limit: usize }
fn read_chunk(data: rawptr, destination: []u8) usize!io.IoErr {
  state := #cast(*Chunk, data)
  state.calls += 1
  take := state.source.len - state.at
  if state.at < state.split && take > state.split - state.at {
    take = state.split - state.at
  }
  if state.limit > 0 && take > state.limit {
    take = state.limit
  }
  if take > destination.len {
    take = destination.len
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
    for capacity in 0..source.len {
      chunk := Chunk{source: source, limit: 1}
      storage: [128]u8
      streamed := xml.stream_scanner(input(&chunk), storage[..capacity])
      event := xml_stream(&streamed)
      if event.value.found || event.failure.kind != 2 {
        #panic("XML short storage")
      }
    }
  }
  for limit in 0..4 {
    for split in 1..source.len + 1 {
      chunk := Chunk{source: source, split: split, limit: limit}
      storage: [128]u8
      capacity := source.len
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
