#!/usr/bin/env python3
"""Build and exercise the native compiler with LLVM tools forbidden (Linux x64)."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    raise SystemExit('This qualification requires an x86-64 Linux host')


def run(command, env, *, success=True):
    result = subprocess.run(list(map(str, command)), cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=180)
    if success:
        assert result.returncode == 0, (command, result.stdout, result.stderr)
    else:
        assert result.returncode != 0, command
    return result


with tempfile.TemporaryDirectory(prefix='dyn-no-llvm-') as directory:
    root = Path(directory)
    forbidden = root / 'forbidden'
    forbidden.write_text('#!/bin/sh\necho "LLVM tool invoked" >&2\nexit 99\n')
    forbidden.chmod(0o755)
    env = dict(os.environ, BUILD=str(root / 'build'), DYN_WITH_LLVM='0',
               CC='gcc', CXX=str(forbidden), LLVM_CONFIG=str(forbidden),
               CLANG=str(forbidden), DYN_SDK=str(ROOT),
               DYN_ASSEMBLY_ORACLE='0', DYN_TEXT_ORACLE='0')
    env.pop('DYN_LINKER', None)
    run(['python3', 'tools/build.py', 'dyn', 'host'], env)
    compiler = root / 'build/dyn'
    dependencies = run(['ldd', compiler], env).stdout.lower()
    assert not any(name in dependencies for name in ('llvm', 'tree-sitter', 'libstdc++', 'libc++')), dependencies
    symbols = run(['nm', '-u', compiler], env).stdout
    assert 'LLVM' not in symbols and 'dyn_thinlto' not in symbols, symbols
    app = root / 'app'
    app.mkdir()
    (app / 'main.dyn').write_text('''use "std/io"
fn identity(value:$T) T { return value }
fn initial() u64 { return 19 }
first:u64=initial()
struct Pair { first:u64, second:u64 }
fn main() {
 value:u64=first
 pair:=Pair{first:identity(value),second:23}
 if pair.first+pair.second!=42 { #panic("native computation") }
 _=io.println(io.stdout(), "no LLVM")
}
''')
    output = root / 'program'
    for mode in ('--debug', '--release'):
        run([compiler, 'build', app, mode, '--quiet', '--no-cache', '--output', output], env)
        assert run([output], env).stdout == 'no LLVM\n'
    # Every registered native object format must work without LLVM linkage.
    for target in ('riscv64-linux', 'x86_64-linux', 'aarch64-linux', 'aarch64-macos', 'x86_64-macos', 'x86_64-windows', 'aarch64-windows'):
        run([compiler, 'build', app, '--quiet', '--no-cache', '--emit-object', '--no-link',
             '--target', target, '--output', output], env)
        data = output.with_suffix('.o').read_bytes()
        if target.endswith('linux'):
            assert data[:4] == b'\x7fELF' and int.from_bytes(data[18:20], 'little') == (243 if target.startswith('riscv') else 62 if target.startswith('x86') else 183)
        elif target.endswith('macos'):
            assert data[:4] == b'\xcf\xfa\xed\xfe'
        else:
            assert data[:2] == (b'\x64\x86' if target.startswith('x86') else b'\x64\xaa')
    # Unsupported modes must fail before producing output, never silently fall back.
    for options in (['--backend', 'llvm'],):
        destination = root / 'unsupported'
        result = run([compiler, 'build', app, '--output', destination, *options], env, success=False)
        assert 'LLVM backend was removed' in result.stderr, result.stderr
        assert not destination.exists()
    env['DYN'] = str(compiler)
    for test in ('lsp-navigation', 'shared-host', 'compiler-contracts', 'aggregate-abi',
                 'panic-lifetime', 'native-release', 'native-optimization', 'native-machine-optimization', 'text-output', 'native-assembly', 'native-decode', 'cross-runtime', 'wasm-independent', 'wrap-enum-values', 'sync-host', 'concurrency-net-host'):
        run(['python3', 'tests/'+test+'.py'], env)
    run(['python3', 'tests/runtime-support.py'], env)
    run(['python3', 'tools/package-sdk.py'], env)
print('PASS LLVM-free GCC build, debug/release execution, shared libraries, seven object targets, LSP and relocated SDK')
