#!/usr/bin/env python3
"""Rules 2 and 3: stubs and length on a miss, results instead of out parameters, typed get and parse."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use mem "std/mem"
use strings "std/strings"
use bytes "std/bytes"
use json "std/encoding/json"
use ini "std/encoding/ini"
use "std/fail"
use io "std/io"
use hex "std/encoding/hex"
use utf8 "std/unicode/utf8"
use time "std/time"
use rand "std/rand"
use text "std/text/scanner"
fn check(ok: bool, message: []const u8) {
  if !ok {
    #panic(message)
  }
}
struct Parsed { root: *const json.Value, failed: bool }
fn parse(arena: *mem.Arena, source: []const u8) Parsed {
  root := json.parse(arena, source) catch { return Parsed{ root: &json.nil_value, failed: true } }
  return Parsed{ root: root }
}
// The failure of a read that must fail: 1 NotFound, 2 InvalidInput, 3 other.
fn code_of(err: io.IoErr) u8 {
  case err {
    .NotFound => { return 1 }
    .InvalidInput => { return 2 }
    _ => { return 3 }
  }
}
fn get_i32_err(object: *const json.Value, key: []const u8) u8 {
  _ = json.get<i32>(object, key) catch err { return code_of(err) }
  return 0
}
fn get_text_err(object: *const json.Value, key: []const u8) u8 {
  _ = json.get<[]const u8>(object, key) catch err { return code_of(err) }
  return 0
}
fn find_err(source: []const u8, section: []const u8, key: []const u8) u8 {
  _ = ini.find(source, section, key) catch err { return code_of(err) }
  return 0
}
fn hex_fails(arena: *mem.Arena, source: []const u8) bool {
  _ = hex.decode(arena, source) catch { return true }
  return false
}
fn f32_of(object: *const json.Value, key: []const u8) f32 {
  return json.get<f32>(object, key) catch { #panic("json f32") }
}
fn i32_of(object: *const json.Value, key: []const u8) i32 {
  return json.get<i32>(object, key) catch { #panic("json i32") }
}
fn main() {
  arena := mem.arena_alloc(0)
  check(strings.parse<u16>("8080") == 8080, "u16")
  check(strings.parse<u8>("256") == 0 && !strings.valid<u8>("256"), "u8 overflow")
  check(strings.parse<i8>("-128") == -128 && strings.parse<i8>("-129") == 0, "i8 range")
  check(strings.parse<i64>("-9223372036854775808") == -9223372036854775807 - 1, "i64 minimum")
  check(strings.parse<u64>("+7") == 7 && strings.parse<u64>("-7") == 0, "signs")
  check(strings.parse<f64>("1.5e2") == 150.0 && strings.parse<f32>("0.5") == 0.5, "floats")
  check(strings.parse<bool>("true") && !strings.parse<bool>("nope") && !strings.valid<bool>("nope"), "bool")
  check(strings.parse<u32>("80o") == 0 && !strings.valid<u32>("80o") && strings.valid<u32>("80"), "garbage")
  check(strings.parse_base<u32>("ff", 16) == 255 && strings.parse_base<u8>("777", 8) == 0, "bases")
  check(strings.parse<isize>("-5") == -5 && strings.parse<usize>("5") == 5, "pointer-sized")
  name := "config.json"
  dot := bytes.find(name, ".")
  check(dot == 6 && bytes.equal(name[..dot], "config"), "find")
  missing := bytes.find(name, "#")
  check(missing == name.len && name[missing..].len == 0, "length on a miss")
  check(bytes.find_last("a/b/c", "/") == 3 && bytes.find_last_byte("abc", 'z') == 3, "find_last")
  check(bytes.contains("abc", "") && !bytes.contains("abc", "d"), "contains")
  parts := bytes.splitter("a,,b", ",")
  count: usize = 0
  for {
    _ = bytes.split_next(&parts)
    if parts.ended {
      break
    }
    count += 1
  }
  check(count == 3, "split pieces")
  lines := strings.scanner("one\r\ntwo")
  first := strings.scan_line(&lines)
  second := strings.scan_line(&lines)
  check(bytes.equal(first, "one") && bytes.equal(second, "two") && !lines.ended, "scanner")
  _ = strings.scan_line(&lines)
  check(lines.ended, "scanner end")
  fields := text.Scanner{ source: "a  bc" }
  check(bytes.equal(text.next_field(&fields), "a") && bytes.equal(text.next_field(&fields), "bc"), "fields")
  doc := parse(arena, "{\"x\": 2.5, \"name\": \"boss\", \"hp\": 40, \"alive\": true, \"tags\": [1, 2]}")
  check(!doc.failed, "json parse")
  check(f32_of(doc.root, "x") == 2.5 && i32_of(doc.root, "hp") == 40, "json numbers")
  name_text := json.get<[]const u8>(doc.root, "name") catch { #panic("json text") }
  alive := json.get<bool>(doc.root, "alive") catch { #panic("json bool") }
  check(bytes.equal(name_text, "boss") && alive, "json text")
  tags := json.get<*const json.Value>(doc.root, "tags") catch { #panic("json tags") }
  tag := json.as<u8>(json.array_get(tags, 1)) catch { #panic("json as") }
  check(json.array_length(tags) == 2 && tag == 2, "json nested")
  check(get_i32_err(doc.root, "nope") == 1, "json missing member")
  check(get_text_err(doc.root, "hp") == 2, "json wrong kind")
  check(get_i32_err(doc.root, "x") == 2, "json not whole")
  // object_get chains through misses without failing.
  nothing := json.object_get(json.object_get(doc.root, "a"), "b")
  check(nothing == &json.nil_value && json.is_missing(nothing) && get_i32_err(nothing, "b") == 1, "json chained miss")
  broken := parse(arena, "{\"x\": ")
  check(broken.failed && get_i32_err(broken.root, "x") == 1, "json failed root")
  port := ini.find("[server]\nport = 80\n", "server", "port") catch { #panic("ini find") }
  check(bytes.equal(port, "80"), "ini find")
  check(find_err("[server]\nport = 80\n", "server", "host") == 1, "ini missing")
  check(find_err("[server\nport = 80\n", "server", "port") == 2, "ini malformed")
  decoded := hex.decode(arena, "abcd") catch { #panic("hex decode") }
  check(decoded.len == 2 && decoded[0] == 171 && hex_fails(arena, "abc"), "hex decode")
  status: fail.Status
  check(utf8.codepoint_count("h\xc3\xa9") == 2 && utf8.codepoint_count("a\xff") == 2, "codepoints")
  walker := utf8.iterator("\xc3\xa9\xff")
  check(utf8.next(&walker) == 233 && utf8.next(&walker) == 0xfffd && !walker.ended, "utf8 next")
  _ = utf8.next(&walker)
  check(walker.ended, "utf8 end")
  date := time.parse_iso8601(&status, "2024-02-29T12:34:56Z")
  impossible: fail.Status
  _ = time.parse_iso8601(&impossible, "2024-02-30")
  check(!status.failed && date.day == 29 && impossible.failed, "iso8601")
  state := rand.State{ value: 1 }
  check(rand.below(&state, 10) < 10, "rand below")
}
'''
UNSIGNED = 'use "std/bytes"\nfn main() {\n  at := bytes.find("abc", "z")\n  if at < 0 {\n    #panic("x")\n  }\n}\n'
with tempfile.TemporaryDirectory(prefix='dyn-typed-reads-') as temporary:
    project = Path(temporary)
    source = project / 'main.dyn'
    output = project / ('program.exe' if os.name == 'nt' else 'program')
    source.write_text(SOURCE)
    for release in (False, True):
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output),
                        *(['--release'] if release else [])], check=True, timeout=90)
        subprocess.run([str(output)], check=True, timeout=10)
    source.write_text(UNSIGNED)
    result = subprocess.run([DYN, 'check', str(project), '--no-cache'], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and 'an unsigned value is never negative' in result.stderr, result.stderr
    source.write_text('use strings "std/strings"\nstruct P { x: i32 }\nfn main() {\n  _ = strings.parse<P>("1")\n}\n')
    subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=90)
    result = subprocess.run([str(output)], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and 'strings.parse: unsupported type' in result.stderr, result.stderr
print('PASS typed reads: strings.parse/valid, json.get, length on a miss, result-returning scanners and decoders (debug/release)')
