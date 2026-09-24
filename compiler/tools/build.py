#!/usr/bin/env python3
"""Incremental native artifacts for the compiler justfile (no Make dependency)."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

COMPILER = Path(__file__).resolve().parents[1]
WORKSPACE = Path(os.environ.get('WORKSPACE', COMPILER.parent)).resolve()
BUILD = Path(os.environ.get('BUILD', WORKSPACE/'build' if (WORKSPACE/'tests/run.sh').is_file() else COMPILER/'build')).resolve()
TS_DIR = Path(os.environ.get('TS_DIR', WORKSPACE/'tree-sitter-dyn')).resolve()

def flags(name, default=''):
    return shlex.split(os.environ.get(name, default))

cc = flags('CC', 'cc')
clang = flags('CLANG', 'clang')
cflags = flags('CFLAGS', '-std=c11 -Wall -Wextra -Wpedantic -Werror -g')
llvm_config = flags('LLVM_CONFIG', 'llvm-config')
def llvm(*args, fallback=''):
    if shutil.which(llvm_config[0]):
        return shlex.split(subprocess.check_output(llvm_config + list(args), text=True))
    return shlex.split(fallback)
cppflags = flags('CPPFLAGS') + llvm('--cflags')
llvm_ldflags = llvm('--ldflags')
llvm_libs = llvm('--link-shared', '--libs', fallback='-lLLVM')
sources = sorted(COMPILER.glob('src/*.c'))
headers = sorted(COMPILER.glob('src/*.h'))
ts_sources = [TS_DIR/'src/parser.c', TS_DIR/'src/scanner.c']
frontend = [COMPILER/'src'/name for name in ('frontend.c', 'ast.c', 'sema.c', 'sema_globals.c', 'source.c', 'source_tree.c', 'diagnostic.c', 'target.c')]
unity = BUILD/'dyn_unity.c'
artifacts = {}
def add(name, inputs, command):
    artifacts[name] = (list(map(Path, inputs)), list(map(str, command)))

add('dyn-release', [unity, *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-O2', '-I.', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', unity, *ts_sources, '-ltree-sitter', *llvm_ldflags, *llvm_libs, '-pthread', '-o', f'{BUILD}/dyn-release'])

add('dyn', [unity, *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-I.', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', unity, *ts_sources, '-ltree-sitter', *llvm_ldflags, *llvm_libs, '-pthread', '-o', f'{BUILD}/dyn'])

add('dynrt_start.o', [f'{COMPILER}/runtime/linux_x86_64_start.S'],
    [*cc, '-c', f'{COMPILER}/runtime/linux_x86_64_start.S', '-o', f'{BUILD}/dynrt_start.o'])

add('dynrt_release.o', [f'{COMPILER}/runtime/linux_x86_64_start.S'],
    [*cc, '-DDYN_RELEASE', '-c', f'{COMPILER}/runtime/linux_x86_64_start.S', '-o', f'{BUILD}/dynrt_release.o'])

add('dynrt_support.o', [f'{COMPILER}/runtime/reference_support.c'],
    [*cc, '-O2', '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-ffunction-sections', '-c', f'{COMPILER}/runtime/reference_support.c', '-o', f'{BUILD}/dynrt_support.o'])

add('dynrt_support_pic.o', [f'{COMPILER}/runtime/reference_support.c'],
    [*cc, '-O2', '-fPIC', '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-ffunction-sections', '-c', f'{COMPILER}/runtime/reference_support.c', '-o', f'{BUILD}/dynrt_support_pic.o'])

add('dynrt_aarch64_support_pic.o', [f'{COMPILER}/runtime/reference_support.c'],
    [*clang, '--target=aarch64-linux-gnu', '-DDYN_AARCH64', '-O2', '-fPIC', '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-ffunction-sections', '-c', f'{COMPILER}/runtime/reference_support.c', '-o', f'{BUILD}/dynrt_aarch64_support_pic.o'])

add('dynrt_shared.o', [f'{COMPILER}/runtime/linux_x86_64_start.S'],
    [*cc, '-DDYN_SHARED', '-DDYN_RELEASE', '-fPIC', '-c', f'{COMPILER}/runtime/linux_x86_64_start.S', '-o', f'{BUILD}/dynrt_shared.o'])

add('dynrt_aarch64_shared.o', [f'{COMPILER}/runtime/linux_aarch64_start.S'],
    [*clang, '--target=aarch64-linux-gnu', '-DDYN_SHARED', '-DDYN_RELEASE', '-fPIC', '-c', f'{COMPILER}/runtime/linux_aarch64_start.S', '-o', f'{BUILD}/dynrt_aarch64_shared.o'])

add('dynrt_aarch64_start.o', [f'{COMPILER}/runtime/linux_aarch64_start.S'],
    [*clang, '--target=aarch64-linux-gnu', '-c', f'{COMPILER}/runtime/linux_aarch64_start.S', '-o', f'{BUILD}/dynrt_aarch64_start.o'])

add('dynrt_aarch64_release.o', [f'{COMPILER}/runtime/linux_aarch64_start.S'],
    [*clang, '--target=aarch64-linux-gnu', '-DDYN_RELEASE', '-c', f'{COMPILER}/runtime/linux_aarch64_start.S', '-o', f'{BUILD}/dynrt_aarch64_release.o'])

add('dynrt_aarch64_support.o', [f'{COMPILER}/runtime/reference_support.c'],
    [*clang, '--target=aarch64-linux-gnu', '-DDYN_AARCH64', '-O2', '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-ffunction-sections', '-c', f'{COMPILER}/runtime/reference_support.c', '-o', f'{BUILD}/dynrt_aarch64_support.o'])

add('dynrt_windows_start.o', [f'{COMPILER}/runtime/windows_x86_64_start.S', f'{COMPILER}/runtime/windows_stack_probe.S'],
    [*clang, '--target=x86_64-pc-windows-msvc', '-c', f'{COMPILER}/runtime/windows_x86_64_start.S', '-o', f'{BUILD}/dynrt_windows_start.o'])

add('dynrt_windows_shared.o', [f'{COMPILER}/runtime/windows_x86_64_start.S', f'{COMPILER}/runtime/windows_stack_probe.S'],
    [*clang, '--target=x86_64-pc-windows-msvc', '-DDYN_SHARED', '-DDYN_RELEASE', '-c', f'{COMPILER}/runtime/windows_x86_64_start.S', '-o', f'{BUILD}/dynrt_windows_shared.o'])

add('dynrt_windows_support.o', [f'{COMPILER}/runtime/reference_support.c'],
    [*clang, '--target=x86_64-pc-windows-msvc', '-DDYN_SINGLE_THREAD', '-O2', '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-ffunction-sections', '-c', f'{COMPILER}/runtime/reference_support.c', '-o', f'{BUILD}/dynrt_windows_support.o'])

add('dynrt_macos_start.o', [f'{COMPILER}/runtime/macos_aarch64_start.S'],
    [*clang, '--target=arm64-apple-macosx', '-c', f'{COMPILER}/runtime/macos_aarch64_start.S', '-o', f'{BUILD}/dynrt_macos_start.o'])

add('dynrt_macos_shared.o', [f'{COMPILER}/runtime/macos_aarch64_start.S'],
    [*clang, '--target=arm64-apple-macosx', '-DDYN_SHARED', '-DDYN_RELEASE', '-c', f'{COMPILER}/runtime/macos_aarch64_start.S', '-o', f'{BUILD}/dynrt_macos_shared.o'])

add('dynrt_macos_support.o', [f'{COMPILER}/runtime/reference_support.c'],
    [*clang, '--target=arm64-apple-macosx', '-DDYN_SINGLE_THREAD', '-DDYN_AARCH64', '-DDYN_RELEASE', '-O2', '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-ffunction-sections', '-c', f'{COMPILER}/runtime/reference_support.c', '-o', f'{BUILD}/dynrt_macos_support.o'])

add('tree-sitter-dyn-parser.o', [f'{TS_DIR}/src/parser.c'],
    [*cc, '-O2', f'-I{TS_DIR}/src', '-c', f'{TS_DIR}/src/parser.c', '-o', f'{BUILD}/tree-sitter-dyn-parser.o'])

add('tree-sitter-dyn-scanner.o', [f'{TS_DIR}/src/scanner.c'],
    [*cc, '-O2', f'-I{TS_DIR}/src', '-c', f'{TS_DIR}/src/scanner.c', '-o', f'{BUILD}/tree-sitter-dyn-scanner.o'])

add('tree-sitter-dyn-bridge.o', [f'{COMPILER}/runtime/tree_sitter_bridge.c'],
    [*cc, '-O2', '-fno-stack-protector', '-c', f'{COMPILER}/runtime/tree_sitter_bridge.c', '-o', f'{BUILD}/tree-sitter-dyn-bridge.o'])

add('llvm-bridge.o', [f'{COMPILER}/runtime/llvm_bridge.c'],
    [*cc, '-O2', '-fno-stack-protector', '-c', f'{COMPILER}/runtime/llvm_bridge.c', '-o', f'{BUILD}/llvm-bridge.o'])

add('dyn-sanitize', [*sources, *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-O1', '-fno-omit-frame-pointer', '-fsanitize=address,undefined', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', *sources, *ts_sources, '-ltree-sitter', *llvm_ldflags, *llvm_libs, '-pthread', '-o', f'{BUILD}/dyn-sanitize'])

add('dynrt_wasm.o', [f'{COMPILER}/runtime/wasm_support.c'],
    [*clang, '--target=wasm32-unknown-unknown', '-O2', '-ffreestanding', '-fno-builtin', '-c', f'{COMPILER}/runtime/wasm_support.c', '-o', f'{BUILD}/dynrt_wasm.o'])

add('dynrt_wasi_start.o', [f'{COMPILER}/runtime/wasi_start.c'],
    [*clang, '--target=wasm32-unknown-wasi', '-O2', '-ffreestanding', '-fno-builtin', '-c', f'{COMPILER}/runtime/wasi_start.c', '-o', f'{BUILD}/dynrt_wasi_start.o'])

add('dynrt_wasi_support.o', [f'{COMPILER}/runtime/wasi_support.c'],
    [*clang, '--target=wasm32-unknown-wasi', '-O2', '-ffreestanding', '-fno-builtin', '-c', f'{COMPILER}/runtime/wasi_support.c', '-o', f'{BUILD}/dynrt_wasi_support.o'])

add('dyn-perf', [unity, *headers, f'{WORKSPACE}/benchmarks/compiler-allocations.c', *ts_sources],
    [*cc, *cppflags, *cflags, '-O2', '-I.', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', unity, 'benchmarks/compiler-allocations.c', *ts_sources, '-ltree-sitter', *llvm_ldflags, *llvm_libs, '-pthread', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/dyn-perf'])

add('cache-failure-test', [f'{WORKSPACE}/tests/cache-failure.c', f'{COMPILER}/src/cache.c', f'{COMPILER}/src/build.c', *headers],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', 'tests/cache-failure.c', f'{COMPILER}/src/build.c', '-pthread', '-o', f'{BUILD}/cache-failure-test'])

add('interface-allocation-test', [f'{WORKSPACE}/tests/interface-allocation.c', f'{COMPILER}/src/interface.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', f'-I{TS_DIR}/src', 'tests/interface-allocation.c', f'{COMPILER}/src/source_tree.c', *ts_sources, '-ltree-sitter', '-o', f'{BUILD}/interface-allocation-test'])

add('module-allocation-test', [f'{WORKSPACE}/tests/interface-allocation.c', f'{COMPILER}/src/module.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-DTEST_MODULE', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', 'tests/interface-allocation.c', f'{COMPILER}/src/source_tree.c', *ts_sources, '-ltree-sitter', '-o', f'{BUILD}/module-allocation-test'])

add('global-allocation-test', [f'{WORKSPACE}/tests/global-allocation.c', f'{COMPILER}/src/sema_globals.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', *headers],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', 'tests/global-allocation.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', *ts_sources, '-ltree-sitter', '-o', f'{BUILD}/global-allocation-test'])

add('source-failure-test', [f'{WORKSPACE}/tests/source-failure.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', *headers],
    [*cc, *cppflags, *cflags, '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', 'tests/source-failure.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', *ts_sources, '-ltree-sitter', '-o', f'{BUILD}/source-failure-test'])

add('ast-allocation-test', [f'{WORKSPACE}/tests/ast-allocation.c', f'{COMPILER}/src/ast.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', f'{COMPILER}/src/target.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', 'tests/ast-allocation.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', f'{COMPILER}/src/target.c', *ts_sources, '-ltree-sitter', '-o', f'{BUILD}/ast-allocation-test'])

add('module-rewrite-allocation-test', [f'{WORKSPACE}/tests/module-rewrite-allocation.c', f'{COMPILER}/src/module_rewrite.c', f'{COMPILER}/src/diagnostic.c', *headers],
    [*cc, *cppflags, *cflags, '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', 'tests/module-rewrite-allocation.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', f'{COMPILER}/src/target.c', *ts_sources, '-ltree-sitter', '-o', f'{BUILD}/module-rewrite-allocation-test'])

add('stack-probe-test', [f'{WORKSPACE}/tests/stack-probe.c', f'{WORKSPACE}/tests/stack-probe.S', f'{COMPILER}/runtime/windows_stack_probe.S'],
    [*cc, *cppflags, *cflags, 'tests/stack-probe.c', 'tests/stack-probe.S', f'{COMPILER}/runtime/windows_stack_probe.S', '-o', f'{BUILD}/stack-probe-test'])

add('frontend-state-test', [f'{WORKSPACE}/tests/frontend-state.c', *frontend, *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', f'{WORKSPACE}/tests/frontend-state.c', *frontend, *ts_sources, '-ltree-sitter', '-pthread', '-o', f'{BUILD}/frontend-state-test'])

add('frontend-failure-test', [f'{WORKSPACE}/tests/frontend-failure.c', f'{WORKSPACE}/tests/fault-alloc.h', *frontend, f'{COMPILER}/src/ir.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', f'{WORKSPACE}/tests/frontend-failure.c', *frontend, f'{COMPILER}/src/ir.c', *ts_sources, '-ltree-sitter', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/frontend-failure-test'])

add('analysis-cache-test', [f'{WORKSPACE}/tests/analysis-cache.c', f'{WORKSPACE}/tests/fault-alloc.h', f'{COMPILER}/src/analysis_cache.c', *frontend, *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', f'{WORKSPACE}/tests/analysis-cache.c', f'{COMPILER}/src/analysis_cache.c', *frontend, *ts_sources, '-ltree-sitter', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/analysis-cache-test'])

add('codegen-failure-test', [f'{WORKSPACE}/tests/frontend-failure.c', f'{WORKSPACE}/tests/fault-alloc.h', *frontend, f'{COMPILER}/src/ir.c', f'{COMPILER}/src/codegen.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-DTEST_CODEGEN', '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', f'{WORKSPACE}/tests/frontend-failure.c', *frontend, f'{COMPILER}/src/ir.c', f'{COMPILER}/src/codegen.c', *ts_sources, '-ltree-sitter', *llvm_ldflags, *llvm_libs, '-pthread', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/codegen-failure-test'])

add('project-failure-test', [f'{WORKSPACE}/tests/project-failure.c', f'{WORKSPACE}/tests/fault-alloc.h', *frontend, f'{COMPILER}/src/module.c', f'{COMPILER}/src/module_rewrite.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', f'{WORKSPACE}/tests/project-failure.c', *frontend, f'{COMPILER}/src/module.c', f'{COMPILER}/src/module_rewrite.c', *ts_sources, '-ltree-sitter', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/project-failure-test'])

add('syntax-cache-test', [f'{WORKSPACE}/tests/syntax-cache.c', f'{WORKSPACE}/tests/fault-alloc.h', f'{COMPILER}/src/source_tree.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', f'-I{TS_DIR}/src', 'tests/syntax-cache.c', *ts_sources, '-ltree-sitter', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/syntax-cache-test'])

add('scope-index-test', [f'{WORKSPACE}/tests/scope-index.c', f'{WORKSPACE}/tests/fault-alloc.h', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', f'-I{TS_DIR}/src', 'tests/scope-index.c', *ts_sources, '-ltree-sitter', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/scope-index-test'])

add('unwind-capacity-test', [f'{WORKSPACE}/tests/unwind-capacity.c', f'{COMPILER}/runtime/reference_support.c'],
    [*cc, *cppflags, *cflags, '-ffreestanding', '-fno-builtin', 'tests/unwind-capacity.c', '-o', f'{BUILD}/unwind-capacity-test'])

add('dyn-per-file', [*sources, *headers, *ts_sources],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', f'-I{TS_DIR}/src', *sources, *ts_sources, '-ltree-sitter', *llvm_ldflags, *llvm_libs, '-pthread', '-o', BUILD/'dyn-per-file'])

add('build-plan-test', [WORKSPACE/'tests/build-plan.c', COMPILER/'src/build.c', *headers],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', WORKSPACE/'tests/build-plan.c', COMPILER/'src/build.c', '-pthread', '-Wl,--wrap=waitpid', '-o', BUILD/'build-plan-test'])
add('interface-test', [WORKSPACE/'tests/interface-cache.c', *[COMPILER/'src'/n for n in ('interface.c', 'source.c', 'source_tree.c', 'diagnostic.c', 'target.c')], *headers, *ts_sources],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', f'-I{TS_DIR}/src', WORKSPACE/'tests/interface-cache.c', *[COMPILER/'src'/n for n in ('interface.c', 'source.c', 'source_tree.c', 'diagnostic.c', 'target.c')], *ts_sources, '-ltree-sitter', '-o', BUILD/'interface-test'])

ALL = ['dynrt_wasi_start.o', 'dynrt_wasi_support.o', 'dynrt_wasm.o', 'dyn', 'dynrt_start.o', 'dynrt_release.o', 'dynrt_support.o', 'dynrt_support_pic.o', 'dynrt_aarch64_support_pic.o', 'dynrt_shared.o', 'dynrt_aarch64_shared.o', 'dynrt_aarch64_start.o', 'dynrt_aarch64_release.o', 'dynrt_aarch64_support.o', 'dynrt_windows_start.o', 'dynrt_windows_support.o', 'dynrt_macos_start.o', 'dynrt_macos_support.o', 'dynrt_windows_shared.o', 'dynrt_macos_shared.o', 'tree-sitter-dyn-parser.o', 'tree-sitter-dyn-scanner.o', 'tree-sitter-dyn-bridge.o', 'llvm-bridge.o']

def write_changed(path, text):
    if not path.exists() or path.read_text() != text:
        path.write_text(text)

def build(name):
    inputs, command = artifacts[name]
    output = BUILD/name
    stamp = BUILD/(name + '.build.json')
    # Header changes, flags, compiler selection and removed source files invalidate
    # artifacts too. Signatures are written only after a successful command.
    if unity in inputs:
        inputs += sources
    executable = shutil.which(command[0])
    if executable:
        inputs.append(Path(executable).resolve())
    inputs += [Path(__file__), COMPILER/'justfile', *TS_DIR.glob('src/tree_sitter/*.h')]
    identity = dict(command=command, inputs={str(p): [p.stat().st_mtime_ns, p.stat().st_size] for p in inputs})
    encoded = json.dumps(identity, sort_keys=True)
    if output.is_file() and stamp.is_file() and stamp.read_text() == encoded:
        return
    print(shlex.join(command), flush=True)
    stamp.unlink(missing_ok=True)
    subprocess.run(command, cwd=WORKSPACE if (WORKSPACE/'tests/run.sh').is_file() else COMPILER, check=True)
    stamp.write_text(encoded)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('targets', nargs='+', choices=[*artifacts, 'all'])
    args = parser.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    # Serialize writers to the same build directory, including recursive recipes.
    import fcntl
    with (BUILD/'.build.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        grammar_inputs = [TS_DIR/'grammar.js', TS_DIR/'tree-sitter.json']
        generated = TS_DIR/'src/parser.c'
        if not generated.exists() or any(p.stat().st_mtime_ns > generated.stat().st_mtime_ns for p in grammar_inputs):
            subprocess.run(['just', '--justfile', str(TS_DIR/'justfile'), 'generate'], check=True)
        write_changed(unity, '#define _POSIX_C_SOURCE 200809L\n' + ''.join(f'#include "{p}"\n' for p in sources))
        targets = dict.fromkeys(n for t in args.targets for n in (ALL if t == 'all' else [t]))
        for name in targets:
            build(name)

if __name__ == '__main__':
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
