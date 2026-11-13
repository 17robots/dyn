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
use "std/io" io
use "std/strings"
use "std/bytes"
fn main() {
  state := lua.create_owned()
  if state == nil {
    #panic("Lua allocation")
  }
  defer lua.destroy_owned(state)
  if io.failed(lua.execute(state, "return 6 * 7").failure) {
    #panic("Lua evaluation")
  }
  answer := lua.integer(state, -1)
  if io.failed(answer.failure) || answer.value != 42 {
    #panic("Lua result")
  }
  if !lua.pop(state, 1) {
    #panic("Lua pop")
  }
  if io.failed(lua.execute(state, "return 'hello'").failure) {
    #panic("Lua string")
  }
  text := lua.bytes(state, -1)
  if io.failed(text.failure) || !bytes.equal(text.value, "hello") {
    #panic("Lua bytes")
  }
  _ = lua.pop(state, 1) // text expires here.
  if !io.failed(lua.execute(state, "return (").failure) || lua.stack_size(state) != 1 {
    #panic("Lua syntax failure")
  }
  _ = lua.pop(state, 1)
  if !io.failed(lua.execute(state, "return missing()").failure) {
    #panic("Lua runtime failure")
  }
  _ = lua.pop(state, 1)
  if lua.stack_size(state) != 0 || lua.pop(state, 1) {
    #panic("Lua stack balance")
  }
  if io.failed(lua.execute(state, "").failure) || lua.stack_size(state) != 1 {
    #panic("empty Lua chunk")
  }
  if !io.failed(lua.bytes(state, -1).failure) || !io.failed(lua.integer(state, 0).failure) {
    #panic("Lua result validation")
  }
  _ = lua.pop(state, 1)
  io.println("Lua: 42; protected syntax/runtime failures; balanced stack")
}
''', 'Lua: 42; protected syntax/runtime failures; balanced stack'),
    'pcre2': ('libpcre2-8', r'''use "vendor/pcre2" regex
use "std/io" io
use "std/strings"
use "std/bytes"
fn main() {
  compiled := regex.compile_owned("name=([a-z]+)", 0)
  if io.failed(compiled.failure) {
    #panic("regex compile")
  }
  defer regex.pattern_destroy_owned(compiled.pattern)
  data := regex.match_data_create_owned(compiled.pattern)
  if data == nil {
    #panic("match allocation")
  }
  defer regex.match_data_destroy_owned(data)
  subject := "name=ada"
  matched := regex.match(compiled.pattern, data, subject, 0)
  if io.failed(matched.failure) || !matched.matched {
    #panic("match")
  }
  span := regex.capture(data, 1)
  if !span.set || !bytes.equal(subject[span.start..span.end], "ada") {
    #panic("capture")
  }
  absent := regex.match(compiled.pattern, data, "123", 0)
  if io.failed(absent.failure) || absent.matched {
    #panic("no-match status")
  }
  if !io.failed(regex.match(compiled.pattern, data, subject, 999).failure) {
    #panic("start validation")
  }
  invalid := regex.compile_owned("(", 0)
  if !io.failed(invalid.failure) {
    regex.pattern_destroy_owned(invalid.pattern)
    #panic("invalid pattern accepted")
  }
  unicode := regex.compile_owned("(.)?", regex.Utf | regex.Ucp)
  if io.failed(unicode.failure) {
    #panic("Unicode compile")
  }
  defer regex.pattern_destroy_owned(unicode.pattern)
  unicode_data := regex.match_data_create_owned(unicode.pattern)
  if unicode_data == nil {
    #panic("Unicode match data")
  }
  defer regex.match_data_destroy_owned(unicode_data)
  bad_utf: [1]u8 = [255]
  if !io.failed(regex.match(unicode.pattern, unicode_data, bad_utf[..], 0).failure) {
    #panic("invalid UTF accepted")
  }
  empty_match := regex.match(unicode.pattern, unicode_data, "", 0)
  if io.failed(empty_match.failure) || !empty_match.matched || regex.capture(unicode_data, 1).set {
    #panic("unset capture")
  }
  io.println("PCRE2: captured ada; no-match and invalid pattern handled")
}
''', 'PCRE2: captured ada; no-match and invalid pattern handled'),
    'sqlite': ('sqlite3', r'''use "vendor/sqlite" sqlite
use "std/io" io

fn main() {
  backing: [128]u8

  opened := sqlite.open(":memory:", backing[..])
  if io.failed(opened.failure) {
    #panic("sqlite open failed")
  }
  if io.failed(sqlite.execute(opened.database, "create table task(id integer);", backing[..])) {
    #panic("sqlite exec failed")
  }
  prepared := sqlite.prepare(opened.database, "insert into task(id) values(?1)")
  if io.failed(prepared.failure) || prepared.empty {
    #panic("sqlite prepare failed")
  }
  insert := prepared.statement
  if io.failed(sqlite.bind_i64(&insert, 1, 42)) || sqlite.step(&insert).state != sqlite.State.Done {
    #panic("sqlite bound insert failed")
  }
  queried := sqlite.prepare(opened.database, "select id from task")
  if io.failed(queried.failure) || queried.empty {
    #panic("sqlite query prepare failed")
  }
  query := queried.statement
  if sqlite.step(&query).state != sqlite.State.Row || sqlite.column(&query, 0).integer != 42 {
    #panic("sqlite row failed")
  }
  if !io.failed(sqlite.prepare(opened.database, "SELECT (").failure) { #panic("invalid SQL") }
  if io.failed(sqlite.finalize(&query)) || query.handle != nil || io.failed(sqlite.finalize(&query)) { #panic("query ownership") }
  if io.failed(sqlite.finalize(&insert)) || insert.handle != nil { #panic("insert ownership") }
  if io.failed(sqlite.close(opened.database)) { #panic("database leaked statements") }
  io.println("sqlite ok")
}
''', 'sqlite ok'),
    'lz4': ('liblz4', r'''use "vendor/lz4"
use "std/io" io
use "std/strings"
use "std/bytes"
fn main() {
  compressed: [128]u8
  output: [128]u8
  source := "caller buffers caller buffers caller buffers"
  result := lz4.compress(compressed[..], source)
  if io.failed(result.failure) {
    #panic("LZ4 compression")
  }
  decoded := lz4.decompress(output[..], compressed[..result.written])
  if io.failed(decoded.failure) || !bytes.equal(output[..decoded.written], source) {
    #panic("LZ4 roundtrip")
  }
  if !io.failed(lz4.decompress(output[..1], compressed[..result.written]).failure) {
    #panic("short output accepted")
  }
  if !io.failed(lz4.compress(compressed[..0], source).failure) {
    #panic("short compressed output accepted")
  }
  invalid: [1]u8 = [255]
  if !io.failed(lz4.decompress(output[..], invalid[..]).failure) {
    #panic("invalid block accepted")
  }
  empty := lz4.compress(compressed[..], "")
  if io.failed(empty.failure) || io.failed(lz4.decompress(output[..0], compressed[..empty.written]).failure) {
    #panic("empty block")
  }
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
