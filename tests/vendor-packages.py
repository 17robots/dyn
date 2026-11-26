#!/usr/bin/env python3
"""Linux native qualification: Lua 5.4, PCRE2-8, SQLite, LZ4 wrappers.

Uses installed providers only. Missing dependencies fail; no downloads/skips.
Recorded versions are pkg-config metadata; this is not all-vendor qualification.
"""
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
DYN = str(Path(os.environ.get('DYN', BUILD/'dyn-release')).resolve())
if platform.system() != 'Linux':
    raise RuntimeError('This provider subset is qualified on native Linux only')

CASES = {
    'lua': ('lua5.4', r'''use "vendor/lua"
use io "std/io"
use "std/strings"
use "std/bytes"
fn fails(state: lua.State, source: []const u8) bool {
  lua.execute(state, source) catch { return true }
  return false
}
fn bytes_fail(state: lua.State, index: i32) bool {
  _ = lua.bytes(state, index) catch { return true }
  return false
}
fn integer_fails(state: lua.State, index: i32) bool {
  _ = lua.integer(state, index) catch { return true }
  return false
}
fn main() {
  state := lua.create_owned() catch { #panic("unexpected failure") }
  defer lua.destroy_owned(state)
  lua.execute(state, "return 6 * 7") catch { #panic("unexpected failure") }
  if (lua.integer(state, -1) catch 0) != 42 {
    #panic("Lua result")
  }
  lua.pop(state, 1) catch { #panic("unexpected failure") }
  lua.execute(state, "return 'hello'") catch { #panic("unexpected failure") }
  if !bytes.equal(lua.bytes(state, -1) catch "", "hello") {
    #panic("Lua bytes")
  }
  lua.pop(state, 1) catch { #panic("unexpected failure") } // the text expires here.
  if !fails(state, "return (") || lua.stack_size(state) != 1 {
    #panic("Lua syntax failure")
  }
  lua.pop(state, 1) catch { #panic("unexpected failure") }
  if !fails(state, "return missing()") {
    #panic("Lua runtime failure")
  }
  lua.pop(state, 1) catch { #panic("unexpected failure") }
  underflow := false
  lua.pop(state, 1) catch { underflow = true }
  if lua.stack_size(state) != 0 || !underflow {
    #panic("Lua stack balance")
  }
  lua.execute(state, "") catch { #panic("unexpected failure") }
  if lua.stack_size(state) != 1 {
    #panic("empty Lua chunk")
  }
  if !bytes_fail(state, -1) || !integer_fails(state, 0) {
    #panic("Lua result validation")
  }
  lua.pop(state, 1) catch { #panic("unexpected failure") }
  io.println("Lua: 42; protected syntax/runtime failures; balanced stack")
}
''', 'Lua: 42; protected syntax/runtime failures; balanced stack'),
    'pcre2': ('libpcre2-8', r'''use regex "vendor/pcre2"
use io "std/io"
use "std/strings"
use "std/bytes"
fn fails(pattern: regex.Pattern, data: regex.MatchData, subject: []const u8, start: usize) bool {
  _ = regex.match(pattern, data, subject, start) catch { return true }
  return false
}
fn compiles(source: []const u8) bool {
  bad := regex.compile_owned(source, 0) catch { return false }
  regex.pattern_destroy_owned(bad)
  return true
}
fn capture_missing(data: regex.MatchData, index: u32) bool {
  _ = regex.capture(data, index) catch err {
    case err {
      .NotFound => { return true }
      _ => { return false }
    }
  }
  return false
}
fn main() {
  pattern := regex.compile_owned("name=([a-z]+)", 0) catch { #panic("unexpected failure") }
  defer regex.pattern_destroy_owned(pattern)
  data := regex.match_data_create_owned(pattern)
  if data == nil {
    #panic("match allocation")
  }
  defer regex.match_data_destroy_owned(data)
  subject := "name=ada"
  if !(regex.match(pattern, data, subject, 0) catch false) {
    #panic("match")
  }
  span := regex.capture(data, 1) catch { #panic("unexpected failure") }
  if !bytes.equal(subject[span.start..span.end], "ada") {
    #panic("capture")
  }
  if (regex.match(pattern, data, "123", 0) catch true) {
    #panic("no-match status")
  }
  if !fails(pattern, data, subject, 999) {
    #panic("start validation")
  }
  if compiles("(") {
    #panic("invalid pattern accepted")
  }
  unicode := regex.compile_owned("(.)?", regex.Utf | regex.Ucp) catch { #panic("unexpected failure") }
  defer regex.pattern_destroy_owned(unicode)
  unicode_data := regex.match_data_create_owned(unicode)
  if unicode_data == nil {
    #panic("Unicode match data")
  }
  defer regex.match_data_destroy_owned(unicode_data)
  bad_utf: [1]u8 = [255]
  if !fails(unicode, unicode_data, bad_utf[..], 0) {
    #panic("invalid UTF accepted")
  }
  if !(regex.match(unicode, unicode_data, "", 0) catch false) {
    #panic("empty match")
  }
  if !capture_missing(unicode_data, 1) {
    #panic("unset capture")
  }
  io.println("PCRE2: captured ada; no-match and invalid pattern handled")
}
''', 'PCRE2: captured ada; no-match and invalid pattern handled'),
    'sqlite': ('sqlite3', r'''use sqlite "vendor/sqlite"
use io "std/io"

fn prepares(database: sqlite.Database, sql: []const u8) bool {
  _ = sqlite.prepare(database, sql) catch { return false }
  return true
}
fn main() {
  backing: [128]u8
  database := sqlite.open(":memory:", backing[..]) catch { #panic("sqlite failed") }
  sqlite.execute(database, "create table task(id integer);", backing[..]) catch { #panic("sqlite failed") }
  inserting := sqlite.prepare(database, "insert into task(id) values(?1)") catch { #panic("sqlite failed") }
  insert := inserting.statement
  sqlite.bind_i64(&insert, 1, 42) catch { #panic("sqlite failed") }
  if (sqlite.step(&insert) catch sqlite.State.Failed) != sqlite.State.Done {
    #panic("sqlite bound insert failed")
  }
  querying := sqlite.prepare(database, "select id from task") catch { #panic("sqlite failed") }
  query := querying.statement
  stepped := sqlite.step(&query) catch { #panic("sqlite row failed") }
  column := sqlite.column(&query, 0) catch { #panic("sqlite row failed") }
  if stepped != sqlite.State.Row || column.integer != 42 {
    #panic("sqlite row failed")
  }
  if prepares(database, "SELECT (") { #panic("invalid SQL") }
  sqlite.finalize(&query)
  sqlite.finalize(&query)
  if query.handle != nil { #panic("query ownership") }
  sqlite.finalize(&insert)
  if insert.handle != nil { #panic("insert ownership") }
  sqlite.close(database) catch { #panic("database leaked statements") }
  io.println("sqlite ok")
}
''', 'sqlite ok'),
    'lz4': ('liblz4', r'''use "vendor/lz4"
use io "std/io"
use "std/strings"
use "std/bytes"
fn compress_fails(destination: []u8, source: []const u8) bool {
  _ = lz4.compress(destination, source) catch { return true }
  return false
}
fn decompress_fails(destination: []u8, source: []const u8) bool {
  _ = lz4.decompress(destination, source) catch { return true }
  return false
}
fn main() {
  compressed: [128]u8
  output: [128]u8
  source := "caller buffers caller buffers caller buffers"
  written := lz4.compress(compressed[..], source) catch { #panic("unexpected failure") }
  decoded := lz4.decompress(output[..], compressed[..written]) catch { #panic("unexpected failure") }
  if !bytes.equal(output[..decoded], source) {
    #panic("LZ4 roundtrip")
  }
  if !decompress_fails(output[..1], compressed[..written]) {
    #panic("short output accepted")
  }
  if !compress_fails(compressed[..0], source) {
    #panic("short compressed output accepted")
  }
  invalid: [1]u8 = [255]
  if !decompress_fails(output[..], invalid[..]) {
    #panic("invalid block accepted")
  }
  empty := lz4.compress(compressed[..], "") catch { #panic("unexpected failure") }
  _ = lz4.decompress(output[..0], compressed[..empty]) catch { #panic("unexpected failure") }
  if lz4.compress_bound(lz4.MaxInput + 1) != 0 {
    #panic("oversized input accepted")
  }
  io.println("LZ4 bounded roundtrip passed")
}
''', 'LZ4 bounded roundtrip passed'),
}

env = dict(os.environ)
report = {'scope': 'Linux Lua 5.4/PCRE2-8/SQLite/LZ4 wrapper lifecycle and errors', 'status': 'running', 'providers': []}
BUILD.mkdir(parents=True, exist_ok=True)
report_path = BUILD/'vendor-packages.json'
try:
    with tempfile.TemporaryDirectory(prefix='dyn-provider-packages-') as temporary:
        work = Path(temporary)
        for name, (package, source, expected) in CASES.items():
            version = subprocess.check_output(['pkg-config', '--modversion', package], env=env, text=True).strip()
            libdir = subprocess.check_output(['pkg-config', '--variable=libdir', package], env=env, text=True).strip()
            provider_env = dict(env)
            for key in ('DYN_LIBRARY_PATH', 'LD_LIBRARY_PATH'):
                provider_env[key] = libdir + (os.pathsep + env[key] if env.get(key) else '')
            project = work/name
            project.mkdir()
            (project/'main.dyn').write_text(source)
            for release in (False, True):
                binary = project/'probe'
                subprocess.run([DYN, 'build', str(project), '--quiet', '--no-cache', '--output', str(binary)] +
                               (['--release'] if release else []), env=provider_env, check=True, timeout=90)
                result = subprocess.run([str(binary)], env=provider_env, capture_output=True, text=True, timeout=15)
                assert result.returncode == 0 and result.stdout == expected+'\n', (name, release, result.returncode, result.stdout, result.stderr)
            report['providers'].append({'provider': name, 'pkg_config_version': version, 'modes': ['debug', 'release']})
            print(f'PASS {name} ({package} metadata {version}): debug/release lifecycle and errors')
    report['status'] = 'passed'
except BaseException as error:
    report.update(status='failed', error=str(error))
    raise
finally:
    report_path.write_text(json.dumps(report, indent=2)+'\n')
