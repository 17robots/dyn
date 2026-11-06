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

SOURCE = r'''use "std/parse" parse
use "std/dynlib" dl
use "std/io" errors
#link("c")
fn check(ok: bool) { if !ok { #panic("dynlib results") } }
fn invalid_open(result: dl.OpenResult) {
  check(result.failure.kind != errors.Kind.Ok && result.value == nil && result.failure.kind == errors.Kind.InvalidInput && result.failure.native == 0 && result.message == nil)
}
fn invalid_symbol(result: dl.SymbolResult, kind: errors.Kind) {
  check(result.failure.kind != errors.Kind.Ok && result.value == nil && result.failure.kind == kind && result.failure.native == 0 && result.message == nil)
}
fn main() {
  zero: dl.OpenResult
  symbol_zero: dl.SymbolResult
  close_zero: dl.Result
  check(zero.value == nil && zero.failure.kind == errors.Kind.Ok && zero.failure.native == 0 && zero.message == nil)
  check(symbol_zero.value == nil && symbol_zero.failure.kind == errors.Kind.Ok && symbol_zero.failure.native == 0 && symbol_zero.message == nil)
  check(close_zero.failure.kind == errors.Kind.Ok && close_zero.failure.native == 0 && close_zero.message == nil)
  native_code: isize = zero.failure.native
  message_pointer: *const u8 = zero.message
  check(native_code == 0 && message_pointer == nil)
  invalid_open(dl.open("bad\x00path", dl.Now))
  long_name: [4096]u8 = []
  invalid_open(dl.open(long_name[..], dl.Now))
  invalid_symbol(dl.symbol(nil, "malloc"), errors.Kind.InvalidState)
  badclose := dl.close(nil)
  check(badclose.failure.kind != errors.Kind.Ok && badclose.failure.kind == errors.Kind.InvalidInput && badclose.failure.native == 0 && badclose.message == nil)
  missing := dl.open(MISSING_PATH, dl.Now)
  check(missing.failure.kind != errors.Kind.Ok && missing.value == nil && missing.failure.kind == errors.Kind.System && missing.failure.native == 0 && missing.message != nil)
  // Inspect borrowed loader storage before any subsequent loader operation.
  description := dl.error_bytes(missing.message, 8192)
  check(description.failure.kind == parse.Kind.Ok && #len(description.value) > 0)
  library := dl.open(LIBC_PATH, dl.Now | dl.Local)
  check(library.failure.kind == errors.Kind.Ok && library.value != nil && library.failure.kind == errors.Kind.Ok && library.failure.native == 0 && library.message == nil)
  invalid_symbol(dl.symbol(library.value, "bad\x00symbol"), errors.Kind.InvalidInput)
  invalid_symbol(dl.symbol(library.value, long_name[..]), errors.Kind.InvalidInput)
  absent := dl.symbol(library.value, "dyn_regression_nonexistent_symbol_17robots")
  check(absent.failure.kind != errors.Kind.Ok && absent.value == nil && absent.failure.kind == errors.Kind.System && absent.failure.native == 0 && absent.message != nil)
  borrowed := dl.error_bytes(absent.message, 8192)
  check(borrowed.failure.kind == parse.Kind.Ok && #len(borrowed.value) > 0)
  found := dl.symbol(library.value, "malloc")
  check(found.failure.kind == errors.Kind.Ok && found.value != nil && found.failure.kind == errors.Kind.Ok && found.failure.native == 0 && found.message == nil)
  closed := dl.close(&library.value)
  check(closed.failure.kind == errors.Kind.Ok && closed.failure.native == 0 && closed.message == nil && library.value == nil)
  twice := dl.close(&library.value)
  check(twice.failure.kind != errors.Kind.Ok && twice.failure.kind == errors.Kind.InvalidState && twice.failure.native == 0 && twice.message == nil && library.value == nil)
  ORACLE
}
'''
ORACLE = r'''
  oracle := dl.open(ORACLE_PATH, dl.Now)
  check(oracle.failure.kind == errors.Kind.Ok && oracle.value != nil && oracle.failure.kind == errors.Kind.Ok && oracle.failure.native == 0 && oracle.message == nil)
  stale := dl.symbol(oracle.value, "missing_before_null")
  check(stale.failure.kind != errors.Kind.Ok && stale.failure.kind == errors.Kind.System && stale.message != nil && stale.failure.native == 0)
  null_symbol := dl.symbol(oracle.value, "dyn_valid_null")
  check(null_symbol.failure.kind == errors.Kind.Ok && null_symbol.value == nil && null_symbol.failure.kind == errors.Kind.Ok && null_symbol.failure.native == 0 && null_symbol.message == nil)
  check(dl.close(&oracle.value).failure.kind == errors.Kind.Ok && oracle.value == nil)
'''

# Only this child process preloads the shim; production std sources are untouched.
CLOSE_SOURCE = r'''use "std/parse" parse
use "std/dynlib" dl
use "std/io" errors
#link("c")
fn check(ok: bool) { if !ok { #panic("dynlib close failure") } }
fn main() {
  library := dl.open(LIBC_PATH, dl.Now)
  check(library.failure.kind == errors.Kind.Ok && library.value != nil)
  owner := library.value
  failed := dl.close(&library.value)
  check(failed.failure.kind != errors.Kind.Ok && failed.failure.kind == errors.Kind.System && failed.failure.native == 0 && failed.message != nil && library.value == owner)
  message := dl.error_bytes(failed.message, 4096)
  check(message.failure.kind == parse.Kind.Ok && #len(message.value) > 0)
  closed := dl.close(&library.value)
  check(closed.failure.kind == errors.Kind.Ok && closed.failure.native == 0 && closed.message == nil && library.value == nil)
  twice := dl.close(&library.value)
  check(twice.failure.kind != errors.Kind.Ok && twice.failure.kind == errors.Kind.InvalidState && twice.failure.native == 0 && twice.message == nil)
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
