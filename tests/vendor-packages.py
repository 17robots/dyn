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
use "std/strings"
use "std/io"
fn main() {
  state := lua.create_owned()
  if state == nil {
    #panic("Lua allocation")
  }
  defer lua.destroy_owned(state)
  if !lua.execute(state, "return 6 * 7").ok {
    #panic("Lua evaluation")
  }
  answer := lua.integer(state, -1)
  if !answer.ok || answer.value != 42 {
    #panic("Lua result")
  }
  if !lua.pop(state, 1) {
    #panic("Lua pop")
  }
  if !lua.execute(state, "return 'hello'").ok {
    #panic("Lua string")
  }
  text := lua.bytes(state, -1)
  if !text.ok || !strings.equal(text.value, "hello") {
    #panic("Lua bytes")
  }
  _ = lua.pop(state, 1) // text expires here.
  if lua.execute(state, "return (").ok || lua.stack_size(state) != 1 {
    #panic("Lua syntax failure")
  }
  _ = lua.pop(state, 1)
  if lua.execute(state, "return missing()").ok {
    #panic("Lua runtime failure")
  }
  _ = lua.pop(state, 1)
  if lua.stack_size(state) != 0 || lua.pop(state, 1) {
    #panic("Lua stack balance")
  }
  if !lua.execute(state, "").ok || lua.stack_size(state) != 1 {
    #panic("empty Lua chunk")
  }
  if lua.bytes(state, -1).ok || lua.integer(state, 0).ok {
    #panic("Lua result validation")
  }
  _ = lua.pop(state, 1)
  _ = io.println(io.stdout(), "Lua: 42; protected syntax/runtime failures; balanced stack")
}
''', 'Lua: 42; protected syntax/runtime failures; balanced stack'),
    'pcre2': ('libpcre2-8', r'''use "vendor/pcre2" regex
use "std/strings"
use "std/io"
fn main() {
  compiled := regex.compile_owned("name=([a-z]+)", 0)
  if !compiled.ok {
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
  if !matched.ok || !matched.matched {
    #panic("match")
  }
  span := regex.capture(data, 1)
  if !span.set || !strings.equal(subject[span.start..span.end], "ada") {
    #panic("capture")
  }
  absent := regex.match(compiled.pattern, data, "123", 0)
  if !absent.ok || absent.matched {
    #panic("no-match status")
  }
  if regex.match(compiled.pattern, data, subject, 999).ok {
    #panic("start validation")
  }
  invalid := regex.compile_owned("(", 0)
  if invalid.ok {
    regex.pattern_destroy_owned(invalid.pattern)
    #panic("invalid pattern accepted")
  }
  unicode := regex.compile_owned("(.)?", regex.Utf | regex.Ucp)
  if !unicode.ok {
    #panic("Unicode compile")
  }
  defer regex.pattern_destroy_owned(unicode.pattern)
  unicode_data := regex.match_data_create_owned(unicode.pattern)
  if unicode_data == nil {
    #panic("Unicode match data")
  }
  defer regex.match_data_destroy_owned(unicode_data)
  bad_utf: [1]u8 = [255]
  if regex.match(unicode.pattern, unicode_data, bad_utf[..], 0).ok {
    #panic("invalid UTF accepted")
  }
  empty_match := regex.match(unicode.pattern, unicode_data, "", 0)
  if !empty_match.ok || !empty_match.matched || regex.capture(unicode_data, 1).set {
    #panic("unset capture")
  }
  _ = io.println(io.stdout(), "PCRE2: captured ada; no-match and invalid pattern handled")
}
''', 'PCRE2: captured ada; no-match and invalid pattern handled'),
    'sqlite': ('sqlite3', r'''use "vendor/sqlite" sqlite
use "std/io" io

fn main() {
  backing: [128]u8 = []

  opened := sqlite.open(":memory:", backing[..])
  if !opened.ok {
    #panic("sqlite open failed")
  }
  if sqlite.execute(opened.database, "create table task(id integer);", backing[..]) != 0 {
    #panic("sqlite exec failed")
  }
  prepared := sqlite.prepare(opened.database, "insert into task(id) values(?1)")
  if !prepared.ok || prepared.empty {
    #panic("sqlite prepare failed")
  }
  insert := prepared.statement
  if sqlite.bind_i64(&insert, 1, 42) != 0 || sqlite.step(&insert).state != sqlite.State.Done {
    #panic("sqlite bound insert failed")
  }
  queried := sqlite.prepare(opened.database, "select id from task")
  if !queried.ok || queried.empty {
    #panic("sqlite query prepare failed")
  }
  query := queried.statement
  if sqlite.step(&query).state != sqlite.State.Row || sqlite.column(&query, 0).integer != 42 {
    #panic("sqlite row failed")
  }
  if sqlite.prepare(opened.database, "SELECT (").ok { #panic("invalid SQL") }
  if sqlite.finalize(&query) != 0 || query.handle != nil || sqlite.finalize(&query) != 0 { #panic("query ownership") }
  if sqlite.finalize(&insert) != 0 || insert.handle != nil { #panic("insert ownership") }
  if sqlite.close(opened.database) != 0 { #panic("database leaked statements") }
  _ = io.println(io.stdout(), "sqlite ok")
}
''', 'sqlite ok'),
    'lz4': ('liblz4', r'''use "vendor/lz4"
use "std/strings"
use "std/io"
fn main() {
  compressed: [128]u8 = []
  output: [128]u8 = []
  source := "caller buffers caller buffers caller buffers"
  result := lz4.compress(compressed[..], source)
  if !result.ok {
    #panic("LZ4 compression")
  }
  decoded := lz4.decompress(output[..], compressed[..result.written])
  if !decoded.ok || !strings.equal(output[..decoded.written], source) {
    #panic("LZ4 roundtrip")
  }
  if lz4.decompress(output[..1], compressed[..result.written]).ok {
    #panic("short output accepted")
  }
  if lz4.compress(compressed[..0], source).ok {
    #panic("short compressed output accepted")
  }
  invalid: [1]u8 = [255]
  if lz4.decompress(output[..], invalid[..]).ok {
    #panic("invalid block accepted")
  }
  empty := lz4.compress(compressed[..], "")
  if !empty.ok || !lz4.decompress(output[..0], compressed[..empty.written]).ok {
    #panic("empty block")
  }
  if lz4.compress_bound(lz4.MaxInput + 1) != 0 {
    #panic("oversized input accepted")
  }
  _ = io.println(io.stdout(), "LZ4 bounded roundtrip passed")
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
