#!/usr/bin/env python3
"""Linux native raw qualification: generated SQLite and zstd bindings only.

Regenerates against installed C headers, validates C/Dyn layouts and native
calls in debug/release. No downloads; missing providers fail. BIND_CLANG selects
the header parser (default clang); CC selects the native adapter compiler.
"""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
DYN = str(Path(os.environ.get('DYN', BUILD/'dyn-release')).resolve())
if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'aarch64'):
    raise RuntimeError('Raw provider qualification requires native Linux x86_64/aarch64')

CASES = {
    'sqlite': r'''path: [9]u8 = [':','m','e','m','o','r','y',':',0]
  database: rawptr = nil
  if raw.sqlite3_open(#cast(*const c.char) &path[0], &database) != raw.SQLITE_OK { #panic("open") }
  query: []const u8 = "SELECT ?1"
  statement: rawptr = nil
  if raw.sqlite3_prepare_v2(database, #cast(*const c.char) &query[0], #cast(i32) #len(query), &statement, nil) != raw.SQLITE_OK { #panic("prepare") }
  payload: [3]u8 = [4,5,6]
  if raw.sqlite3_bind_blob(statement, 1, #cast(rawptr) &payload[0], 3, #cast(raw.sqlite3_destructor_type) raw.SQLITE_TRANSIENT()) != raw.SQLITE_OK { #panic("bind") }
  payload[0] = 99
  if raw.sqlite3_step(statement) != raw.SQLITE_ROW || raw.sqlite3_column_bytes(statement, 0) != 3 { #panic("row") }
  borrowed := #cast(*const u8) raw.sqlite3_column_blob(statement, 0)
  if borrowed == nil || borrowed.* != 4 { #panic("transient binding must copy") }
  // Borrow ends before reset/finalize. Never access borrowed after this point.
  if raw.sqlite3_reset(statement) != raw.SQLITE_OK { #panic("reset") }
  invalid: []const u8 = "SELECT ("
  rejected: rawptr = nil
  if raw.sqlite3_prepare_v2(database, #cast(*const c.char) &invalid[0], #cast(i32) #len(invalid), &rejected, nil) == raw.SQLITE_OK || rejected != nil { #panic("syntax failure") }
  if raw.sqlite3_finalize(statement) != raw.SQLITE_OK || raw.sqlite3_close(database) != raw.SQLITE_OK { #panic("cleanup") }''',
    'zstd': r'''input: [64]u8 = [] encoded: [256]u8 = [] decoded: [64]u8 = []
  i: usize = 0 for i < #len(input) { input[i] = #cast(u8) i i += 1 }
  n := raw.ZSTD_compress(#cast(rawptr) &encoded[0], 256, #cast(rawptr) &input[0], 64, 3)
  if raw.ZSTD_isError(n) != 0 || raw.ZSTD_decompress(#cast(rawptr) &decoded[0], 64, #cast(rawptr) &encoded[0], n) != 64 { #panic("zstd roundtrip") }
  i = 0 for i < #len(input) { if input[i] != decoded[i] { #panic("zstd bytes") } i += 1 }
  if raw.ZSTD_isError(raw.ZSTD_decompress(#cast(rawptr) &decoded[0], 1, #cast(rawptr) &encoded[0], n)) == 0 { #panic("short output") }
  if raw.ZSTD_isError(raw.ZSTD_decompress(#cast(rawptr) &decoded[0], 64, #cast(rawptr) &encoded[0], n - 1)) == 0 { #panic("truncated frame") }''',
}

report = {'scope': 'Linux SQLite/zstd generated ABI and ownership/error cases', 'status': 'running', 'providers': []}
BUILD.mkdir(parents=True, exist_ok=True)
try:
    with tempfile.TemporaryDirectory(prefix='dyn-native-raw-') as temporary:
        work = Path(temporary)
        sdk = work/'sdk'
        subprocess.run([sys.executable, str(ROOT/'tools/bind-vendors.py'), 'sqlite', 'zstd',
                        '--output', str(sdk), '--dyn', DYN,
                        '--clang', os.environ.get('BIND_CLANG', 'clang'),
                        '--cc', os.environ.get('CC', 'cc')], check=True, timeout=180)
        env = dict(os.environ, DYN_SDK=str(sdk))
        for key in ('DYN_LIBRARY_PATH', 'LD_LIBRARY_PATH'):
            env[key] = str(sdk/'lib') + (os.pathsep + env[key] if env.get(key) else '')
        for name, body in CASES.items():
            project = work/name
            project.mkdir()
            (project/'main.dyn').write_text('use "vendor/'+name+'/raw" raw\nuse "std/c"\nfn main() { if !raw.verify_layout() { #panic("layout") }\n'+body+'\n}\n')
            for release in (False, True):
                binary = project/'probe'
                subprocess.run([DYN, 'build', str(project), '--quiet', '--no-cache', '--output', str(binary)] +
                               (['--release'] if release else []), env=env, check=True, timeout=90)
                subprocess.run([str(binary)], env=env, check=True, timeout=15)
            coverage = json.loads((sdk/'vendor'/name/'raw/coverage.json').read_text())
            report['providers'].append({'provider': name, 'pkg_config_version': coverage['provider_version'],
                                        'abi_fingerprint': coverage['abi_fingerprint'], 'functions': coverage['emitted_functions'],
                                        'modes': ['debug', 'release']})
            print(f"PASS raw {name} (provider metadata {coverage['provider_version']}): debug/release ABI and errors")
    report['status'] = 'passed'
except BaseException as error:
    report.update(status='failed', error=str(error))
    raise
finally:
    (BUILD/'vendor-raw.json').write_text(json.dumps(report, indent=2)+'\n')
