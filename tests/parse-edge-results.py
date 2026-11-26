#!/usr/bin/env python3
"""Portable URL/semver errors, exact offsets, and arena rollback."""
import os
from pathlib import Path
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
SOURCE = r'''use semver "std/semver"
use url "std/net/url"
use parse "std/parse"
use mem "std/mem"
use strings "std/strings"
use "std/bytes"
fn semver_failure(input: []const u8) parse.ParseErr {
  _ = semver.parse(input) catch err { return err }
  #panic("semver should fail")
}
fn too_large(err: parse.ParseErr) bool {
  case err {
    .TooLarge(_) => { return true }
    _ => { return false }
  }
}
// The offset of a malformed input; TooLarge is no answer here.
fn invalid_at(err: parse.ParseErr) usize {
  case err {
    .Invalid(offset) => { return offset }
    .TooLarge(offset) => { #panic("unexpected TooLarge") }
  }
}
fn url_offset(input: []const u8) usize {
  _ = url.parse(input) catch err { return invalid_at(err) }
  #panic("url should fail")
}
fn decode_offset(arena: *mem.Arena, input: []const u8) usize {
  _ = url.percent_decode(arena, input) catch err { return invalid_at(err) }
  #panic("decode should fail")
}
fn main() {
  good := semver.parse("1.2.3-alpha.1+build") catch { #panic("semver valid") }
  if good.major != 1 { #panic("semver valid") }
  for input in ["", "01.2.3", "1", "1.x.3", "1.2", "1.2.x", "1.2.3-", "1.2.3+", "1.2.3x", "1.2.3-01"] {
    if too_large(semver_failure(input)) { #panic("semver invalid") }
  }
  if parse.offset(semver_failure("1.2.3-alpha.x!")) != 13 || parse.offset(semver_failure("01.2.3")) != 1 { #panic("semver offending byte") }
  if parse.offset(semver_failure("")) != 0 { #panic("semver zero") }
  for input in ["4294967296.2.3", "1.4294967296.3", "1.2.4294967296"] {
    if !too_large(semver_failure(input)) { #panic("semver overflow") }
  }
  parsed := url.parse("https://example.com/p?q#f") catch { #panic("url valid") }
  if !bytes.equal(parsed.path, "/p") { #panic("url valid") }
  for input in [":x", "1:x", "a!:x"] {
    _ = url_offset(input)
  }
  if url_offset(":x") != 0 || url_offset("a!:x") != 1 { #panic("url offset") }
  backing: [128+mem.ArenaBufferOverhead]u8
  arena := mem.arena_from_buffer(backing[..])
  _ = mem.push_bytes(arena, 7)
  mark := mem.arena_mark(arena)
  for input in ["%", "%0", "%gg", "%0g"] {
    if decode_offset(arena, input) != 0 || mem.arena_mark(arena) != mark { #panic("decode zero rollback") }
  }
  for input in ["abc%", "abc%0", "abc%gg", "abc%0g"] {
    if decode_offset(arena, input) != 3 || mem.arena_mark(arena) != mark { #panic("decode offset rollback") }
  }
  good_decode := url.percent_decode(arena, "a%20b+") catch { #panic("decode success") }
  if !bytes.equal(good_decode, "a b+") || mem.arena_mark(arena) != mark + 4 { #panic("decode success ownership") }
  encoded := url.percent_encode(arena, "a b/")
  if !bytes.equal(encoded, "a%20b%2f") || mem.arena_mark(arena) != mark + 12 { #panic("encode ownership") }
  empty := url.percent_decode(arena, "") catch { #panic("decode empty") }
  if empty.len != 0 { #panic("decode empty") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-parse-edges-') as directory:
    work = Path(directory)
    (work/'main.dyn').write_text(SOURCE)
    for mode in ('debug', 'release'):
        subprocess.run([DYN, 'build', str(work), '--'+mode, '--quiet', '--no-cache', '--output', str(work/'test')], check=True, timeout=120)
        result = subprocess.run([str(work/'test')], capture_output=True, timeout=10)
        assert result.returncode == 0, (result.stdout, result.stderr)
        print('PASS URL/semver portable result contracts '+mode, flush=True)
