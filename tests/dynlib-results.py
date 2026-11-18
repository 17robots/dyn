#!/usr/bin/env python3
"""Linux loader results; all generated native fixtures live in this test's directory."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

if sys.platform != 'linux':
    print('SKIP dynlib results: this loader oracle is Linux only; see platform-parity.py', flush=True)
    raise SystemExit(0)

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve()
CC = shlex.split(os.environ.get('CC', 'cc'))
if not CC or not shutil.which(CC[0]):
    print('SKIP dynlib results: C compiler required to resolve actual libc path', flush=True)
    raise SystemExit(0)
libc_query = subprocess.run(CC + ['-print-file-name=libc.so.6'], check=True, capture_output=True, text=True, timeout=30).stdout.strip()
libc = Path(libc_query).resolve()
if libc_query == 'libc.so.6' or not libc.is_file():
    raise RuntimeError('C compiler did not resolve libc.so.6: ' + libc_query)

HELPERS = r'''use "std/fail"
use "std/dynlib" dl
#link("c")
struct Opened { value: dl.Handle, failure: fail.Failure }
fn open(path: []const u8, flags: i32) Opened {
  status: fail.Status
  value := dl.open(&status, path, flags)
  return Opened{ value: value, failure: status.failure }
}
struct Found { value: rawptr, failure: fail.Failure }
fn symbol(handle: dl.Handle, name: []const u8) Found {
  status: fail.Status
  value := dl.symbol(&status, handle, name)
  return Found{ value: value, failure: status.failure }
}
fn close(handle: *dl.Handle) fail.Failure {
  status: fail.Status
  dl.close(&status, handle)
  return status.failure
}
fn described(failure: *const fail.Failure) bool {
  return #len(fail.message_text(failure)) > 0
}
'''
SOURCE = HELPERS + r'''fn check(ok: bool) { if !ok { #panic("dynlib results") } }
fn invalid_open(result: Opened) {
  check(result.value == nil && result.failure.kind == fail.Kind.InvalidInput && result.failure.native == 0)
}
fn invalid_symbol(result: Found, kind: fail.Kind) {
  check(result.value == nil && result.failure.kind == kind && result.failure.native == 0)
}
fn main() {
  invalid_open(open("bad\x00path", dl.Now))
  long_name: [4096]u8
  invalid_open(open(long_name[..], dl.Now))
  invalid_symbol(symbol(nil, "malloc"), fail.Kind.InvalidState)
  nothing: dl.Handle
  badclose := close(&nothing)
  check(badclose.kind == fail.Kind.InvalidState && badclose.native == 0)
  missing := open(MISSING_PATH, dl.Now)
  check(missing.value == nil && missing.failure.kind == fail.Kind.System && missing.failure.native == 0 && described(&missing.failure))
  library := open(LIBC_PATH, dl.Now | dl.Local)
  check(library.failure.kind == fail.Kind.Ok && library.value != nil)
  invalid_symbol(symbol(library.value, "bad\x00symbol"), fail.Kind.InvalidInput)
  invalid_symbol(symbol(library.value, long_name[..]), fail.Kind.InvalidInput)
  absent := symbol(library.value, "dyn_regression_nonexistent_symbol_17robots")
  check(absent.value == nil && absent.failure.kind == fail.Kind.System && absent.failure.native == 0 && described(&absent.failure))
  found := symbol(library.value, "malloc")
  check(found.failure.kind == fail.Kind.Ok && found.value != nil)
  closed := close(&library.value)
  check(closed.kind == fail.Kind.Ok && library.value == nil)
  twice := close(&library.value)
  check(twice.kind == fail.Kind.InvalidState && twice.native == 0 && library.value == nil)
  ORACLE
}
'''
ORACLE = r'''
  oracle := open(ORACLE_PATH, dl.Now)
  check(oracle.failure.kind == fail.Kind.Ok && oracle.value != nil)
  stale := symbol(oracle.value, "missing_before_null")
  check(stale.failure.kind == fail.Kind.System && described(&stale.failure) && stale.failure.native == 0)
  null_symbol := symbol(oracle.value, "dyn_valid_null")
  check(null_symbol.failure.kind == fail.Kind.Ok && null_symbol.value == nil)
  check(close(&oracle.value).kind == fail.Kind.Ok && oracle.value == nil)
'''

# Only this child process preloads the shim; production std sources are untouched.
CLOSE_SOURCE = HELPERS + r'''fn check(ok: bool) { if !ok { #panic("dynlib close failure") } }
fn main() {
  library := open(LIBC_PATH, dl.Now)
  check(library.failure.kind == fail.Kind.Ok && library.value != nil)
  owner := library.value
  failed := close(&library.value)
  check(failed.kind == fail.Kind.System && failed.native == 0 && described(&failed) && library.value == owner)
  closed := close(&library.value)
  check(closed.kind == fail.Kind.Ok && library.value == nil)
  twice := close(&library.value)
  check(twice.kind == fail.Kind.InvalidState && twice.native == 0)
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-dynlib-results-') as directory:
    work = Path(directory)
    # Absolute ELF symbol zero is independently verified through libdl by C.
    native = work / 'oracle.c'
    native.write_text('''#include <dlfcn.h>
__asm__(".globl dyn_valid_null\\n.set dyn_valid_null, 0");
int main(int argc, char **argv) {
    if (argc != 2) return 1;
    void *h = dlopen(argv[1], RTLD_NOW);
    if (!h) return 2;
    dlerror();
    void *p = dlsym(h, "dyn_valid_null");
    if (p != 0 || dlerror() != 0) return 3;
    return dlclose(h) != 0;
}
''', encoding='utf-8')
    shared = work / 'oracle.so'
    oracle = work / 'oracle'
    subprocess.run(CC + ['-shared', '-fPIC', str(native), '-o', str(shared), '-ldl'], check=True, timeout=30)
    subprocess.run(CC + [str(native), '-o', str(oracle), '-ldl'], check=True, timeout=30)
    subprocess.run([str(oracle), str(shared)], check=True, timeout=10)
    source = SOURCE.replace('ORACLE', ORACLE.replace('ORACLE_PATH', json.dumps(str(shared))))
    source = source.replace('LIBC_PATH', json.dumps(str(libc))).replace('MISSING_PATH', json.dumps(str(work / 'missing-library.so')))
    (work / 'main.dyn').write_text(source, encoding='utf-8')
    for mode in ('debug', 'release'):
        output = work / ('dynlib-' + mode)
        subprocess.run([str(DYN), 'build', str(work), '--' + mode, '--quiet', '--no-cache', '--output', str(output)], cwd=ROOT, env=dict(os.environ, DYN_SDK=str(ROOT)), check=True, timeout=120)
        subprocess.run([str(output)], check=True, timeout=15)
        print('PASS dynlib results ' + mode + ' (' + str(libc) + ')', flush=True)

    shim_c = work / 'close-shim.c'
    shim_c.write_text('''#define _GNU_SOURCE
#include <dlfcn.h>
static int failed, pending;
int dlclose(void *handle) {
    if (!failed++) { pending = 1; return -1; }
    int (*real_close)(void *) = (int (*)(void *))dlsym(RTLD_NEXT, "dlclose");
    return real_close ? real_close(handle) : -1;
}
char *dlerror(void) {
    if (pending) { pending = 0; return "injected close failure"; }
    return 0;
}
''', encoding='utf-8')
    shim = work / 'close-shim.so'
    subprocess.run(CC + ['-shared', '-fPIC', str(shim_c), '-o', str(shim), '-ldl'], check=True, timeout=30)
    (work / 'main.dyn').write_text(CLOSE_SOURCE.replace('LIBC_PATH', json.dumps(str(libc))), encoding='utf-8')
    for mode in ('debug', 'release'):
        output = work / ('close-failure-' + mode)
        subprocess.run([str(DYN), 'build', str(work), '--' + mode, '--quiet', '--no-cache', '--output', str(output)], cwd=ROOT, env=dict(os.environ, DYN_SDK=str(ROOT)), check=True, timeout=120)
        subprocess.run([str(output)], env=dict(os.environ, LD_PRELOAD=str(shim)), check=True, timeout=15)
        print('PASS dynlib close failure ownership ' + mode, flush=True)
