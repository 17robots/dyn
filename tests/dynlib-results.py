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

HELPERS = r'''use dl "std/dynlib"
use io "std/io"
#link("c")
// The kinds of failure these fixtures meet; Ok when a call worked.
enum Kind { Ok, NotFound, PermissionDenied, AlreadyExists, InvalidInput, WouldBlock, Interrupted, Unsupported, Capacity, System }
fn kind_of(err: io.IoErr) Kind {
 case err {
  .NotFound => { return Kind.NotFound }
  .PermissionDenied => { return Kind.PermissionDenied }
  .AlreadyExists => { return Kind.AlreadyExists }
  .InvalidInput => { return Kind.InvalidInput }
  .WouldBlock => { return Kind.WouldBlock }
  .Interrupted => { return Kind.Interrupted }
  .Unsupported => { return Kind.Unsupported }
  .Capacity => { return Kind.Capacity }
  .System => { return Kind.System }
 }
}
struct Failure { kind: Kind, native: isize }
fn failure_of(err: io.IoErr) Failure {
  case err {
    .System(code) => { return Failure{ kind: Kind.System, native: code } }
    _ => { return Failure{ kind: kind_of(err) } }
  }
}
struct Opened { value: dl.Handle, failure: Failure }
fn open(path: []const u8, flags: i32) Opened {
  value := dl.open(path, flags) catch err { return Opened{ failure: failure_of(err) } }
  return Opened{ value: value }
}
struct Found { value: rawptr, failure: Failure }
fn symbol(handle: dl.Handle, name: []const u8) Found {
  value := dl.symbol(handle, name) catch err { return Found{ failure: failure_of(err) } }
  return Found{ value: value }
}
fn close(handle: *dl.Handle) Failure {
  dl.close(handle) catch err { return failure_of(err) }
  return Failure{}
}
'''
SOURCE = HELPERS + r'''fn check(ok: bool) { if !ok { #panic("dynlib results") } }
fn invalid_open(result: Opened) {
  check(result.value == nil && result.failure.kind == Kind.InvalidInput && result.failure.native == 0)
}
fn invalid_symbol(result: Found, kind: Kind) {
  check(result.value == nil && result.failure.kind == kind && result.failure.native == 0)
}
fn main() {
  invalid_open(open("bad\x00path", dl.Now))
  long_name: [4096]u8
  invalid_open(open(long_name[..], dl.Now))
  invalid_symbol(symbol(nil, "malloc"), Kind.InvalidInput)
  nothing: dl.Handle
  badclose := close(&nothing)
  check(badclose.kind == Kind.InvalidInput && badclose.native == 0)
  missing := open(MISSING_PATH, dl.Now)
  check(missing.value == nil && missing.failure.kind == Kind.NotFound)
  library := open(LIBC_PATH, dl.Now | dl.Local)
  check(library.failure.kind == Kind.Ok && library.value != nil)
  invalid_symbol(symbol(library.value, "bad\x00symbol"), Kind.InvalidInput)
  invalid_symbol(symbol(library.value, long_name[..]), Kind.InvalidInput)
  absent := symbol(library.value, "dyn_regression_nonexistent_symbol_17robots")
  check(absent.value == nil && absent.failure.kind == Kind.NotFound)
  found := symbol(library.value, "malloc")
  check(found.failure.kind == Kind.Ok && found.value != nil)
  closed := close(&library.value)
  check(closed.kind == Kind.Ok && library.value == nil)
  twice := close(&library.value)
  check(twice.kind == Kind.InvalidInput && twice.native == 0 && library.value == nil)
  ORACLE
}
'''
ORACLE = r'''
  oracle := open(ORACLE_PATH, dl.Now)
  check(oracle.failure.kind == Kind.Ok && oracle.value != nil)
  stale := symbol(oracle.value, "missing_before_null")
  check(stale.failure.kind == Kind.NotFound)
  null_symbol := symbol(oracle.value, "dyn_valid_null")
  check(null_symbol.failure.kind == Kind.Ok && null_symbol.value == nil)
  check(close(&oracle.value).kind == Kind.Ok && oracle.value == nil)
'''

# Only this child process preloads the shim; production std sources are untouched.
CLOSE_SOURCE = HELPERS + r'''fn check(ok: bool) { if !ok { #panic("dynlib close failure") } }
fn main() {
  library := open(LIBC_PATH, dl.Now)
  check(library.failure.kind == Kind.Ok && library.value != nil)
  owner := library.value
  failed := close(&library.value)
  check(failed.kind == Kind.InvalidInput && library.value == owner)
  closed := close(&library.value)
  check(closed.kind == Kind.Ok && library.value == nil)
  twice := close(&library.value)
  check(twice.kind == Kind.InvalidInput && twice.native == 0)
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
