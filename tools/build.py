#!/usr/bin/env python3
"""Incremental native artifacts for the compiler justfile (no Make dependency)."""
import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import json
import os
import re
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import platform

COMPILER = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('BUILD', COMPILER/'build')).resolve()
TS_DIR = Path(os.environ.get('TS_DIR', COMPILER/'build/deps/tree-sitter-dyn')).resolve()

def flags(name, default=''):
    return shlex.split(os.environ.get(name, default))

cc = flags('CC', 'cc')
clang = flags('CLANG', 'clang')
cflags = flags('CFLAGS', '-std=c11 -Wall -Wextra -Wpedantic -Werror -g')
if os.name != 'nt':
    # host.h exposes POSIX helpers even in independently compiled test units.
    cflags += ['-D_POSIX_C_SOURCE=200809L']
version = os.environ.get('DYN_VERSION', '0.1.0-dev')
if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?', version):
    sys.exit('DYN_VERSION must be a semantic version without build metadata')
if sys.platform == 'darwin':
    cflags += ['-D_DARWIN_C_SOURCE']
cflags += ['-DDYN_VERSION="' + version + '"']
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
artifacts = {}
requires = {}
def add(name, inputs, command, needs=()):
    artifacts[name] = (list(map(Path, inputs)), list(map(str, command)))
    requires[name] = list(needs)

# One object per source file lets independent units compile in parallel and
# recompiles only edited files; the grammar objects are shared by both links.
# CPPFLAGS may carry linker search paths (Homebrew does); clang rejects those
# as unused under -Werror in compile-only commands, so pass them to the link.
def is_link_flag(flag):
    return flag.startswith(('-L', '-l', '-Wl,'))
object_cppflags = [f for f in cppflags if not is_link_flag(f)]
link_cppflags = [f for f in cppflags if is_link_flag(f)]

def compiler_objects(kind, optimize):
    names = []
    for source in sources:
        name = f'obj/{kind}/{source.stem}.o'
        add(name, [source, *headers],
            [*cc, *object_cppflags, *cflags, *optimize, f'-I{COMPILER}/src', f'-I{TS_DIR}/src', '-c', source, '-o', BUILD/name])
        names.append(name)
    return names + ['tree-sitter-dyn-parser.o', 'tree-sitter-dyn-scanner.o']

def compiler_link(name, objects):
    add(name, [BUILD/o for o in objects],
        [*cc, *cflags, *[BUILD/o for o in objects], *link_cppflags, '-ltree-sitter', *llvm_ldflags, *llvm_libs, '-pthread', '-o', BUILD/name],
        objects)

compiler_link('dyn-release', compiler_objects('release', ['-O2']))
compiler_link('dyn', compiler_objects('debug', []))

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
    [*cc, '-DDYN_SHARED', '-fPIC', '-c', f'{COMPILER}/runtime/linux_x86_64_start.S', '-o', f'{BUILD}/dynrt_shared.o'])

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
    [*clang, '--target=wasm32-wasip1', '-O2', '-ffreestanding', '-fno-builtin', '-c', f'{COMPILER}/runtime/wasi_start.c', '-o', f'{BUILD}/dynrt_wasi_start.o'])

add('dynrt_wasi_support.o', [f'{COMPILER}/runtime/wasi_support.c'],
    [*clang, '--target=wasm32-wasip1', '-O2', '-ffreestanding', '-fno-builtin', '-c', f'{COMPILER}/runtime/wasi_support.c', '-o', f'{BUILD}/dynrt_wasi_support.o'])

add('cache-failure-test', [f'{COMPILER}/tests/cache-failure.c', f'{COMPILER}/src/cache.c', f'{COMPILER}/src/build.c', *headers],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', 'tests/cache-failure.c', f'{COMPILER}/src/build.c', '-pthread', '-o', f'{BUILD}/cache-failure-test'])

add('interface-allocation-test', [f'{COMPILER}/tests/interface-allocation.c', f'{COMPILER}/src/interface.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', f'-I{TS_DIR}/src', 'tests/interface-allocation.c', f'{COMPILER}/src/source_tree.c', *ts_sources, '-ltree-sitter', '-o', f'{BUILD}/interface-allocation-test'])

add('module-allocation-test', [f'{COMPILER}/tests/interface-allocation.c', f'{COMPILER}/src/module.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-DTEST_MODULE', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', 'tests/interface-allocation.c', f'{COMPILER}/src/source_tree.c', *ts_sources, '-ltree-sitter', '-o', f'{BUILD}/module-allocation-test'])

add('global-allocation-test', [f'{COMPILER}/tests/global-allocation.c', f'{COMPILER}/src/sema_globals.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', *headers],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', 'tests/global-allocation.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', *ts_sources, '-ltree-sitter', '-o', f'{BUILD}/global-allocation-test'])

add('source-failure-test', [f'{COMPILER}/tests/source-failure.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', *headers],
    [*cc, *cppflags, *cflags, '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', 'tests/source-failure.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', *ts_sources, '-ltree-sitter', '-o', f'{BUILD}/source-failure-test'])

add('ast-allocation-test', [f'{COMPILER}/tests/ast-allocation.c', f'{COMPILER}/src/ast.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', f'{COMPILER}/src/target.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', 'tests/ast-allocation.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', f'{COMPILER}/src/target.c', *ts_sources, '-ltree-sitter', '-o', f'{BUILD}/ast-allocation-test'])

add('module-rewrite-allocation-test', [f'{COMPILER}/tests/module-rewrite-allocation.c', f'{COMPILER}/src/module_rewrite.c', f'{COMPILER}/src/diagnostic.c', *headers],
    [*cc, *cppflags, *cflags, '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', 'tests/module-rewrite-allocation.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', f'{COMPILER}/src/target.c', *ts_sources, '-ltree-sitter', '-o', f'{BUILD}/module-rewrite-allocation-test'])

add('stack-probe-test', [f'{COMPILER}/tests/stack-probe.c', f'{COMPILER}/tests/stack-probe.S', f'{COMPILER}/runtime/windows_stack_probe.S'],
    [*cc, *cppflags, *cflags, 'tests/stack-probe.c', 'tests/stack-probe.S', f'{COMPILER}/runtime/windows_stack_probe.S', '-o', f'{BUILD}/stack-probe-test'])

add('frontend-state-test', [f'{COMPILER}/tests/frontend-state.c', *frontend, *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', f'{COMPILER}/tests/frontend-state.c', *frontend, *ts_sources, '-ltree-sitter', '-pthread', '-o', f'{BUILD}/frontend-state-test'])

add('frontend-failure-test', [f'{COMPILER}/tests/frontend-failure.c', f'{COMPILER}/tests/fault-alloc.h', *frontend, f'{COMPILER}/src/ir.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', f'{COMPILER}/tests/frontend-failure.c', *frontend, f'{COMPILER}/src/ir.c', *ts_sources, '-ltree-sitter', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/frontend-failure-test'])

add('analysis-cache-test', [f'{COMPILER}/tests/analysis-cache.c', f'{COMPILER}/tests/fault-alloc.h', f'{COMPILER}/src/analysis_cache.c', *frontend, *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', f'{COMPILER}/tests/analysis-cache.c', f'{COMPILER}/src/analysis_cache.c', *frontend, *ts_sources, '-ltree-sitter', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/analysis-cache-test'])

add('codegen-failure-test', [f'{COMPILER}/tests/frontend-failure.c', f'{COMPILER}/tests/fault-alloc.h', *frontend, f'{COMPILER}/src/ir.c', f'{COMPILER}/src/codegen.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-DTEST_CODEGEN', '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', f'{COMPILER}/tests/frontend-failure.c', *frontend, f'{COMPILER}/src/ir.c', f'{COMPILER}/src/codegen.c', *ts_sources, '-ltree-sitter', *llvm_ldflags, *llvm_libs, '-pthread', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/codegen-failure-test'])

add('project-failure-test', [f'{COMPILER}/tests/project-failure.c', f'{COMPILER}/tests/fault-alloc.h', *frontend, f'{COMPILER}/src/module.c', f'{COMPILER}/src/module_rewrite.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'-I{TS_DIR}/src', f'{COMPILER}/tests/project-failure.c', *frontend, f'{COMPILER}/src/module.c', f'{COMPILER}/src/module_rewrite.c', *ts_sources, '-ltree-sitter', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/project-failure-test'])

add('syntax-cache-test', [f'{COMPILER}/tests/syntax-cache.c', f'{COMPILER}/tests/fault-alloc.h', f'{COMPILER}/src/source_tree.c', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', f'-I{TS_DIR}/src', 'tests/syntax-cache.c', *ts_sources, '-ltree-sitter', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/syntax-cache-test'])

add('scope-index-test', [f'{COMPILER}/tests/scope-index.c', f'{COMPILER}/tests/fault-alloc.h', *headers, *ts_sources],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', f'-I{TS_DIR}/src', 'tests/scope-index.c', *ts_sources, '-ltree-sitter', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/scope-index-test'])

add('unwind-capacity-test', [f'{COMPILER}/tests/unwind-capacity.c', f'{COMPILER}/runtime/reference_support.c'],
    [*cc, *cppflags, *cflags, '-ffreestanding', '-fno-builtin', 'tests/unwind-capacity.c', '-o', f'{BUILD}/unwind-capacity-test'])

add('dyn-per-file', [*sources, *headers, *ts_sources],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', f'-I{TS_DIR}/src', *sources, *ts_sources, '-ltree-sitter', *llvm_ldflags, *llvm_libs, '-pthread', '-o', BUILD/'dyn-per-file'])

add('build-plan-test', [COMPILER/'tests/build-plan.c', COMPILER/'src/build.c', *headers],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', COMPILER/'tests/build-plan.c', COMPILER/'src/build.c', '-pthread', '-Wl,--wrap=waitpid', '-o', BUILD/'build-plan-test'])
add('interface-test', [COMPILER/'tests/interface-cache.c', *[COMPILER/'src'/n for n in ('interface.c', 'source.c', 'source_tree.c', 'diagnostic.c', 'target.c')], *headers, *ts_sources],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', f'-I{TS_DIR}/src', COMPILER/'tests/interface-cache.c', *[COMPILER/'src'/n for n in ('interface.c', 'source.c', 'source_tree.c', 'diagnostic.c', 'target.c')], *ts_sources, '-ltree-sitter', '-o', BUILD/'interface-test'])

ALL = ['dynrt_wasi_start.o', 'dynrt_wasi_support.o', 'dynrt_wasm.o', 'dyn', 'dynrt_start.o', 'dynrt_release.o', 'dynrt_support.o', 'dynrt_support_pic.o', 'dynrt_aarch64_support_pic.o', 'dynrt_shared.o', 'dynrt_aarch64_shared.o', 'dynrt_aarch64_start.o', 'dynrt_aarch64_release.o', 'dynrt_aarch64_support.o', 'dynrt_windows_start.o', 'dynrt_windows_support.o', 'dynrt_macos_start.o', 'dynrt_macos_support.o', 'dynrt_windows_shared.o', 'dynrt_macos_shared.o', 'tree-sitter-dyn-parser.o', 'tree-sitter-dyn-scanner.o', 'tree-sitter-dyn-bridge.o', 'llvm-bridge.o']

HOST = ['dyn-release'] + (
    ['dynrt_windows_start.o', 'dynrt_windows_support.o', 'dynrt_windows_shared.o'] if sys.platform == 'win32' else
    ['dynrt_macos_start.o', 'dynrt_macos_support.o', 'dynrt_macos_shared.o'] if sys.platform == 'darwin' else
    ['dynrt_aarch64_start.o', 'dynrt_aarch64_release.o', 'dynrt_aarch64_support.o', 'dynrt_aarch64_shared.o', 'dynrt_aarch64_support_pic.o'] if platform.machine() == 'aarch64' else
    ['dynrt_start.o', 'dynrt_release.o', 'dynrt_support.o', 'dynrt_shared.o', 'dynrt_support_pic.o'])
if sys.platform == 'win32':
    for name, (inputs, command) in artifacts.items():
        if name.startswith('dyn') and not name.endswith('.o'):
            command[-1] += '.exe'


def write_changed(path, text):
    if not path.exists() or path.read_text() != text:
        path.write_text(text)

def build(name):
    inputs, command = artifacts[name]
    inputs = list(inputs)
    output = BUILD/(name + ('.exe' if sys.platform == 'win32' and name.startswith('dyn') and not name.endswith('.o') else ''))
    stamp = BUILD/(name + '.build.json')
    # Header changes, flags, compiler selection and removed source files invalidate
    # artifacts too. Signatures are written only after a successful command.
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
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(command, cwd=COMPILER, check=True)
    stamp.write_text(encoded)

def build_all(names, jobs):
    # Artifacts write distinct outputs, so anything whose requirements are
    # built can run concurrently. After a failure, finish running work only.
    order = {}
    def visit(name):
        for need in requires[name]:
            visit(need)
        order.setdefault(name)
    for name in names:
        visit(name)
    done, running, failure = set(), {}, None
    with ThreadPoolExecutor(jobs) as pool:
        while order or running:
            if failure is None:
                for name in [n for n in order if all(r in done for r in requires[n])]:
                    del order[name]
                    running[pool.submit(build, name)] = name
            elif not running:
                break
            finished, _ = wait(running, return_when=FIRST_COMPLETED)
            for future in finished:
                name = running.pop(future)
                try:
                    future.result()
                    done.add(name)
                except Exception as error:
                    failure = failure or error
    if failure is not None:
        raise failure

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('targets', nargs='+', choices=[*artifacts, 'all', 'host'])
    parser.add_argument('--jobs', type=int, default=int(os.environ.get('JOBS', os.cpu_count() or 1)))
    args = parser.parse_args()
    BUILD.mkdir(parents=True, exist_ok=True)
    # Serialize writers to the same build directory, including recursive recipes.
    with (BUILD/'.build.lock').open('w') as lock:
        if sys.platform == 'win32':
            import msvcrt
            lock.write('0'); lock.flush(); lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        if not all(path.is_file() for path in ts_sources):
            sys.exit('Missing generated grammar; run just deps or set TS_DIR to a grammar checkout')
        write_changed(BUILD/'libSystem.tbd', (COMPILER/'runtime/libSystem.tbd').read_text())
        targets = dict.fromkeys(n for t in args.targets for n in (ALL if t == 'all' else HOST if t == 'host' else [t]))
        build_all(targets, max(1, args.jobs))

if __name__ == '__main__':
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
