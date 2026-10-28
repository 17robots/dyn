#!/usr/bin/env python3
"""Rules 2 and 3: stubs and length on a miss, results instead of out parameters, typed get and parse."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
SOURCE = r'''use "std/mem" mem
use "std/strings" strings
use "std/bytes" bytes
use "std/encoding/json" json
use "std/encoding/hex" hex
use "std/unicode/utf8" utf8
use "std/time" time
use "std/rand" rand
use "std/text/scanner" text
fn check(ok: bool, message: []const u8) {
  if !ok {
    #panic(message)
  }
}
fn main() {
  arena := mem.arena_create(0)
  check(strings.parse(u16, "8080") == 8080, "u16")
  check(strings.parse(u8, "256") == 0 && !strings.valid(u8, "256"), "u8 overflow")
  check(strings.parse(i8, "-128") == -128 && strings.parse(i8, "-129") == 0, "i8 range")
  check(strings.parse(i64, "-9223372036854775808") == -9223372036854775807 - 1, "i64 minimum")
  check(strings.parse(u64, "+7") == 7 && strings.parse(u64, "-7") == 0, "signs")
  check(strings.parse(f64, "1.5e2") == 150.0 && strings.parse(f32, "0.5") == 0.5, "floats")
  check(strings.parse(bool, "true") && !strings.parse(bool, "nope") && !strings.valid(bool, "nope"), "bool")
  check(strings.parse(u32, "80o") == 0 && !strings.valid(u32, "80o") && strings.valid(u32, "80"), "garbage")
  check(strings.parse_base(u32, "ff", 16) == 255 && strings.parse_base(u8, "777", 8) == 0, "bases")
  check(strings.parse(isize, "-5") == -5 && strings.parse(usize, "5") == 5, "pointer-sized")
  name := "config.json"
  dot := strings.find(name, ".")
  check(dot == 6 && strings.equal(name[..dot], "config"), "find")
  missing := strings.find(name, "#")
  check(missing == #len(name) && #len(name[missing..]) == 0, "length on a miss")
  check(bytes.find_last("a/b/c", "/") == 3 && bytes.find_last_byte("abc", 'z') == 3, "find_last")
  check(bytes.contains("abc", "") && !bytes.contains("abc", "d"), "contains")
  parts := bytes.splitter("a,,b", ",")
  count: usize = 0
  for {
    piece := bytes.split_next(&parts)
    if !piece.ok {
      break
    }
    count += 1
  }
  check(count == 3, "split pieces")
  lines := strings.scanner("one\r\ntwo")
  first := strings.scan_line(&lines)
  second := strings.scan_line(&lines)
  check(first.ok && strings.equal(first.value, "one") && strings.equal(second.value, "two"), "scanner")
  check(!strings.scan_line(&lines).ok, "scanner end")
  fields := text.Scanner{ source: "a  bc" }
  check(strings.equal(text.next_field(&fields).value, "a") && strings.equal(text.next_field(&fields).value, "bc"), "fields")
  doc := json.parse(arena, "{\"x\": 2.5, \"name\": \"boss\", \"hp\": 40, \"alive\": true, \"tags\": [1, 2]}")
  check(doc.ok, "json parse")
  check(json.get(f32, doc.root, "x") == 2.5 && json.get(i32, doc.root, "hp") == 40, "json numbers")
  check(strings.equal(json.get([]const u8, doc.root, "name"), "boss") && json.get(bool, doc.root, "alive"), "json text")
  tags := json.get(*const json.Value, doc.root, "tags")
  check(json.array_length(tags) == 2 && json.as(u8, json.array_get(tags, 1)) == 2, "json nested")
  check(json.get(i32, doc.root, "nope") == 0 && #len(json.get([]const u8, doc.root, "hp")) == 0, "json misses")
  nothing := json.get(*const json.Value, json.get(*const json.Value, doc.root, "a"), "b")
  check(nothing == &json.nil_value && json.is_missing(nothing) && !json.is_null(nothing), "json chained miss")
  broken := json.parse(arena, "{\"x\": ")
  check(!broken.ok && broken.root == &json.nil_value && json.get(i32, broken.root, "x") == 0, "json failed root")
  decoded := hex.decode(arena, "abcd")
  check(decoded.ok && #len(decoded.value) == 2 && decoded.value[0] == 171 && !hex.decode(arena, "abc").ok, "hex decode")
  check(utf8.codepoint_count("h\xc3\xa9").value == 2 && !utf8.codepoint_count("\xff").ok, "codepoints")
  walker := utf8.iterator("\xc3\xa9")
  check(utf8.next(&walker).value == 233 && !utf8.next(&walker).ok, "utf8 next")
  date := time.parse_iso8601("2024-02-29T12:34:56Z")
  check(date.ok && date.value.day == 29 && !time.parse_iso8601("2024-02-30").ok, "iso8601")
  state := rand.State{ value: 1 }
  check(rand.below(&state, 10) < 10, "rand below")
}
'''
UNSIGNED = 'use "std/strings" strings\nfn main() {\n  at := strings.find("abc", "z")\n  if at < 0 {\n    #panic("x")\n  }\n}\n'
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
    source.write_text('use "std/strings" strings\nstruct P { x: i32 }\nfn main() {\n  _ = strings.parse(P, "1")\n}\n')
    subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=90)
    result = subprocess.run([str(output)], capture_output=True, text=True, timeout=10)
    assert result.returncode != 0 and 'strings.parse: unsupported type' in result.stderr, result.stderr
print('PASS typed reads: strings.parse/valid, json.get, length on a miss, result-returning scanners and decoders (debug/release)')
