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
use "std/fail"
use "std/io" io
use "std/strings"
use "std/bytes"
fn fails(state: lua.State, source: []const u8) bool {
  status: fail.Status
  lua.execute(&status, state, source)
  return status.failed
}
fn main() {
  status := fail.Status{ on_failure: fail.panic_on_failure }
  state := lua.create_owned(&status)
  defer lua.destroy_owned(state)
  lua.execute(&status, state, "return 6 * 7")
  if lua.integer(&status, state, -1) != 42 {
    #panic("Lua result")
  }
  lua.pop(&status, state, 1)
  lua.execute(&status, state, "return 'hello'")
  if !bytes.equal(lua.bytes(&status, state, -1), "hello") {
    #panic("Lua bytes")
  }
  lua.pop(&status, state, 1) // the text expires here.
  if !fails(state, "return (") || lua.stack_size(state) != 1 {
    #panic("Lua syntax failure")
  }
  lua.pop(&status, state, 1)
  if !fails(state, "return missing()") {
    #panic("Lua runtime failure")
  }
  lua.pop(&status, state, 1)
  underflow: fail.Status
  lua.pop(&underflow, state, 1)
  if lua.stack_size(state) != 0 || !underflow.failed {
    #panic("Lua stack balance")
  }
  lua.execute(&status, state, "")
  if lua.stack_size(state) != 1 {
    #panic("empty Lua chunk")
  }
  not_text: fail.Status
  _ = lua.bytes(&not_text, state, -1)
  no_slot: fail.Status
  _ = lua.integer(&no_slot, state, 0)
  if !not_text.failed || !no_slot.failed {
    #panic("Lua result validation")
  }
  lua.pop(&status, state, 1)
  io.println("Lua: 42; protected syntax/runtime failures; balanced stack")
}
''', 'Lua: 42; protected syntax/runtime failures; balanced stack'),
    'pcre2': ('libpcre2-8', r'''use "vendor/pcre2" regex
use "std/fail"
use "std/io" io
use "std/strings"
use "std/bytes"
fn fails(pattern: regex.Pattern, data: regex.MatchData, subject: []const u8, start: usize) bool {
  status: fail.Status
  _ = regex.match(&status, pattern, data, subject, start)
  return status.failed
}
fn main() {
  status := fail.Status{ on_failure: fail.panic_on_failure }
  pattern := regex.compile_owned(&status, "name=([a-z]+)", 0)
  defer regex.pattern_destroy_owned(pattern)
  data := regex.match_data_create_owned(pattern)
  if data == nil {
    #panic("match allocation")
  }
  defer regex.match_data_destroy_owned(data)
  subject := "name=ada"
  if !regex.match(&status, pattern, data, subject, 0) {
    #panic("match")
  }
  span := regex.capture(data, 1)
  if !span.found || !bytes.equal(subject[span.start..span.end], "ada") {
    #panic("capture")
  }
  if regex.match(&status, pattern, data, "123", 0) {
    #panic("no-match status")
  }
  if !fails(pattern, data, subject, 999) {
    #panic("start validation")
  }
  invalid: fail.Status
  bad := regex.compile_owned(&invalid, "(", 0)
  if !invalid.failed {
    regex.pattern_destroy_owned(bad)
    #panic("invalid pattern accepted")
  }
  unicode := regex.compile_owned(&status, "(.)?", regex.Utf | regex.Ucp)
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
  if !regex.match(&status, unicode, unicode_data, "", 0) || regex.capture(unicode_data, 1).found {
    #panic("unset capture")
  }
  io.println("PCRE2: captured ada; no-match and invalid pattern handled")
}
''', 'PCRE2: captured ada; no-match and invalid pattern handled'),
    'sqlite': ('sqlite3', r'''use "vendor/sqlite" sqlite
use "std/fail"
use "std/io" io

fn main() {
  backing: [128]u8
  status: fail.Status
  database := sqlite.open(&status, ":memory:", backing[..])
  sqlite.execute(&status, database, "create table task(id integer);", backing[..])
  insert := sqlite.prepare(&status, database, "insert into task(id) values(?1)").statement
  sqlite.bind_i64(&status, &insert, 1, 42)
  if sqlite.step(&status, &insert) != sqlite.State.Done {
    #panic("sqlite bound insert failed")
  }
  query := sqlite.prepare(&status, database, "select id from task").statement
  if sqlite.step(&status, &query) != sqlite.State.Row || sqlite.column(&status, &query, 0).integer != 42 {
    #panic("sqlite row failed")
  }
  if status.failed { #panic("sqlite failed") }
  invalid: fail.Status
  _ = sqlite.prepare(&invalid, database, "SELECT (")
  if !invalid.failed { #panic("invalid SQL") }
  sqlite.finalize(&query)
  sqlite.finalize(&query)
  if query.handle != nil { #panic("query ownership") }
  sqlite.finalize(&insert)
  if insert.handle != nil { #panic("insert ownership") }
  sqlite.close(&status, database)
  if status.failed { #panic("database leaked statements") }
  io.println("sqlite ok")
}
''', 'sqlite ok'),
    'lz4': ('liblz4', r'''use "vendor/lz4"
use "std/fail"
use "std/io" io
use "std/strings"
use "std/bytes"
fn compress_fails(destination: []u8, source: []const u8) bool {
  status: fail.Status
  _ = lz4.compress(&status, destination, source)
  return status.failed
}
fn decompress_fails(destination: []u8, source: []const u8) bool {
  status: fail.Status
  _ = lz4.decompress(&status, destination, source)
  return status.failed
}
fn main() {
  compressed: [128]u8
  output: [128]u8
  status := fail.Status{ on_failure: fail.panic_on_failure }
  source := "caller buffers caller buffers caller buffers"
  written := lz4.compress(&status, compressed[..], source)
  decoded := lz4.decompress(&status, output[..], compressed[..written])
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
  empty := lz4.compress(&status, compressed[..], "")
  _ = lz4.decompress(&status, output[..0], compressed[..empty])
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
