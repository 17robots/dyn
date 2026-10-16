#!/usr/bin/env python3
"""Prune unreachable private native functions without changing exported/FFI roots."""
import ctypes
import os
from pathlib import Path
import platform
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
SOURCE = '''extern fn invoke "fixture_invoke"(callback: *fn(u64) u64, value: u64) u64
initialized: u64 = initialize_value()
cleanups: u64
const callback: *fn(u64) u64 = &recursive_callback
fn initialize_value() u64 { return 5 }
fn recursive_callback(n: u64) u64 { if n == 0 { return 3 } return recursive_callback(n - 1) }
fn ffi_callback(n: u64) u64 { return n + 2 }
fn deferred_cleanup() { cleanups += 1 }
fn scoped_cleanup() { defer deferred_cleanup() }
fn export_helper() u64 { return 4 }
pub fn exported_value() u64 { return initialized + export_helper() }
fn unreachable_private_marker() u64 { return 777 }
fn unreachable_cycle_one() u64 { return unreachable_cycle_two() }
fn unreachable_cycle_two() u64 { return unreachable_cycle_one() }
fn main() {
  scoped_cleanup()
  if initialized != 5 || cleanups != 1 || callback(4) != 3 || invoke(&ffi_callback, 7) != 9 { #panic("reachability") }
}
'''


def run(*args):
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, (args, result.stderr)
    return result


with tempfile.TemporaryDirectory(prefix='dyn-native-reachability-') as directory:
    work = Path(directory)
    module = work/'src'
    module.mkdir()
    (module/'main.dyn').write_text(SOURCE)
    for target in ('x86_64-linux', 'aarch64-linux', 'riscv64-linux', 'x86_64-windows',
                   'aarch64-windows', 'x86_64-macos', 'aarch64-macos'):
        for mode in ('debug', 'release'):
            output = work/f'{target}-{mode}'
            run(DYN, 'build', module, '--'+mode, '--no-cache', '--no-link', '--emit-object',
                '--target', target, '--output', output)
            data = Path(str(output)+'.o').read_bytes()
            for name in ('unreachable_private_marker', 'unreachable_cycle_one', 'unreachable_cycle_two'):
                assert name.encode() not in data, (target, mode, name)
            for name in ('initialize_value', 'recursive_callback', 'ffi_callback', 'deferred_cleanup', 'exported_value', 'export_helper'):
                assert name.encode() in data, (target, mode, name)
    if platform.system() == 'Linux' and platform.machine() == 'x86_64':
        (work/'callback.c').write_text('#include <stdint.h>\nuint64_t fixture_invoke(uint64_t (*f)(uint64_t),uint64_t n) {return f(n);}\n')
        run(*shlex.split(os.environ.get('CC', 'cc')), '-fPIC', '-c', work/'callback.c', '-o', work/'callback.o')
        for mode in ('debug', 'release'):
            output = work/mode
            run(DYN, 'build', module, '--'+mode, '--no-cache', '--link', work/'callback.o', '--output', output)
            run(output)
            library = work/(mode+'.so')
            run(DYN, 'build', module, '--'+mode, '--no-cache', '--shared', '--link', work/'callback.o', '--output', library)
            loaded = ctypes.CDLL(str(library))
            loaded.exported_value.restype = ctypes.c_uint64
            assert loaded.exported_value() == 9
    (module/'main.dyn').write_text('fn unreachable_error() u64 { return true }\nfn main() {}\n')
    result = subprocess.run([str(DYN), 'build', str(module), '--release', '--no-cache',
                             '--output', str(work/'invalid')], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0 and 'error' in result.stderr, result.stderr
print('PASS seven-target reachability: exports, FFI/address callbacks, recursion, deferred cleanup, global initialization and dead-source diagnostics')
