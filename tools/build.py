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
# LLVM is an interchange format only; every compiler uses independent emission.
if os.environ.get('DYN_WITH_LLVM', '0') != '0':
    sys.exit('LLVM backend was removed; omit DYN_WITH_LLVM or set it to 0')
cppflags = flags('CPPFLAGS')
cflags += ['-DDYN_NO_LLVM']
sources = sorted(COMPILER.glob('src/*.c'))
headers = sorted(COMPILER.glob('src/*.h')) + sorted(COMPILER.glob('src/*.inc'))
parser_sources = [COMPILER/'src/parser.c', COMPILER/'src/snapshot.c']
frontend = [COMPILER/'src'/name for name in ('frontend.c', 'ast.c', 'sema.c', 'sema_globals.c', 'source.c', 'source_tree.c', 'diagnostic.c', 'target.c')] + parser_sources
artifacts = {}
requires = {}
def add(name, inputs, command, needs=()):
    artifacts[name] = (list(map(Path, inputs)), list(map(str, command)))
    requires[name] = list(needs)

if sys.platform in ('win32', 'darwin') or platform.machine() == 'aarch64':
    clang = cc

# One object per source file lets independent units compile in parallel and
# recompiles only edited files.
# CPPFLAGS may carry linker search paths (Homebrew does); clang rejects those
# as unused under -Werror in compile-only commands, so pass them to the link.
def is_link_flag(flag):
    return flag.startswith(('-L', '-l', '-Wl,'))
object_cppflags = [f for f in cppflags if not is_link_flag(f)]
link_cppflags = [f for f in cppflags if is_link_flag(f)]
# GCC's Windows runtime must be static in packaged compilers. This is a
# link option, and Clang's compiler-rt toolchain does not consume it.
if sys.platform == 'win32':
    compiler_version = subprocess.check_output([*cc, '--version'], text=True)
    if 'clang' not in compiler_version.lower():
        link_cppflags += ['-static-libgcc']

def compiler_objects(kind, optimize, extra_sources=(), extra_inputs=()):
    names = []
    for source in [*sources, *extra_sources]:
        name = f'obj/{kind}/{source.stem}.o'
        add(name, [source, *headers, *extra_inputs, *([COMPILER/'src/codegen.c', COMPILER/'tools/backend-experiment/output.h'] if source.name == 'codegen_text.c' else [])],
            [*cc, *object_cppflags, *cflags, *optimize, f'-I{COMPILER}/src', '-c', source, '-o', BUILD/name])
        names.append(name)
    return names

def compiler_link(name, objects):
    add(name, [BUILD/o for o in objects],
        [*cc, *cflags, *[BUILD/o for o in objects], *link_cppflags, '-pthread', '-o', BUILD/name],
        objects)

# Native emission also bootstraps portable runtime support on every host.
backend_experiment = COMPILER/'tools/backend-experiment'
native_flags = ['-DDYN_NATIVE_BACKEND']
native_sources = [backend_experiment/'compiler.c', backend_experiment/'dwarf.c']
native_inputs = [backend_experiment/'vector.inc', backend_experiment/'allocation.inc', backend_experiment/'driver.c', backend_experiment/'isa.inc', backend_experiment/'a64.inc', backend_experiment/'rv64.inc',
                 backend_experiment/'coff.inc', backend_experiment/'macho.inc',
                 backend_experiment/'elf64.h', backend_experiment/'output.h', backend_experiment/'dwarf.h']
default_flags = native_flags
default_sources = native_sources
default_inputs = native_inputs
compiler_link('dyn-release', compiler_objects('release', ['-O2', *default_flags],
    default_sources, default_inputs))
compiler_link('dyn', compiler_objects('debug', default_flags, default_sources, default_inputs))

# Matched prepared-IR benchmark harness. Not installed or part of normal builds.
backend_benchmark_objects = [f'obj/release/{name}.o' for name in
    ('frontend', 'ast', 'sema', 'sema_globals', 'source', 'source_tree',
     'diagnostic', 'target', 'ir', 'codegen', 'codegen_text', 'llvm_text', 'native_asm', 'codegen_wasm', 'link_elf', 'link_macho', 'link_coff', 'link_wasm', 'parser', 'snapshot')]
add('obj/benchmark/backend.o',
    [backend_experiment/'benchmark-driver.c', *native_inputs, *headers],
    [*cc, *object_cppflags, *cflags, '-O2', f'-I{COMPILER}/src',
     '-c', backend_experiment/'benchmark-driver.c', '-o', BUILD/'obj/benchmark/backend.o'])
compiler_link('backend-benchmark', [*backend_benchmark_objects, 'obj/benchmark/backend.o',
    'obj/release/compiler.o', 'obj/release/dwarf.o'])


# Runtime objects are portable build products: no target C compiler/assembler.
NATIVE_STARTUPS = [
    'dynrt_start.o', 'dynrt_release.o', 'dynrt_shared.o',
    'dynrt_riscv64_start.o', 'dynrt_riscv64_release.o', 'dynrt_riscv64_shared.o',
    'dynrt_aarch64_start.o', 'dynrt_aarch64_release.o', 'dynrt_aarch64_shared.o',
    'dynrt_windows_start.o', 'dynrt_windows_shared.o', 'dynrt_windows_arm64_start.o', 'dynrt_windows_arm64_shared.o',
    'dynrt_macos_start.o', 'dynrt_macos_shared.o', 'dynrt_macos_x64_start.o', 'dynrt_macos_x64_shared.o']
for name in NATIVE_STARTUPS:
    add(name, [COMPILER/'tools/native-runtime.py', *sorted(COMPILER.glob('runtime/*.S'))],
        [sys.executable, COMPILER/'tools/native-runtime.py', '--output', BUILD/name])
NATIVE_SUPPORT = {
    'dynrt_support.o': 'x86_64-linux', 'dynrt_support_pic.o': 'x86_64-linux',
    'dynrt_riscv64_support.o': 'riscv64-linux', 'dynrt_riscv64_support_pic.o': 'riscv64-linux',
    'dynrt_aarch64_support.o': 'aarch64-linux', 'dynrt_aarch64_support_pic.o': 'aarch64-linux',
    'dynrt_windows_support.o': 'x86_64-windows', 'dynrt_windows_arm64_support.o': 'aarch64-windows', 'dynrt_macos_support.o': 'aarch64-macos', 'dynrt_macos_x64_support.o': 'x86_64-macos'}
for name, target in NATIVE_SUPPORT.items():
    compiler = BUILD/('dyn-release.exe' if sys.platform == 'win32' else 'dyn-release')
    add(name, [COMPILER/'tools/build-native-support.py', *sorted(COMPILER.glob('runtime/support/*.dyn')), compiler],
        [sys.executable, COMPILER/'tools/build-native-support.py', '--compiler', compiler,
         '--target', target, '--output', BUILD/name], needs=['dyn-release'])

add('dyn-sanitize', [*sources, *headers, *native_sources, *native_inputs],
    [*cc, *cppflags, *cflags, *native_flags, '-O1', '-fno-omit-frame-pointer', '-fsanitize=address,undefined', f'-I{COMPILER}/src', *sources, *native_sources, '-pthread', '-o', f'{BUILD}/dyn-sanitize'])

# Wasm runtime objects are generated directly; no target C compiler is needed.
WASM_RUNTIME = ['dynrt_wasm.o', 'dynrt_wasi_start.o', 'dynrt_wasi_support.o']
for name in WASM_RUNTIME:
    add(name, [COMPILER/'tools/wasm-runtime.py'],
        [sys.executable, COMPILER/'tools/wasm-runtime.py', '--output', BUILD/name])

add('llvm-text-unit-test', [COMPILER/'tests/llvm-text-unit.c', COMPILER/'src/llvm_text.c',
    COMPILER/'tools/backend-experiment/output.h', *headers],
    [*cc, *cflags, COMPILER/'tests/llvm-text-unit.c', '-o', BUILD/'llvm-text-unit-test'])

add('cache-failure-test', [f'{COMPILER}/tests/cache-failure.c', f'{COMPILER}/src/cache.c', f'{COMPILER}/src/build.c', *headers],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', 'tests/cache-failure.c', f'{COMPILER}/src/build.c', '-pthread', '-o', f'{BUILD}/cache-failure-test'])

add('interface-allocation-test', [f'{COMPILER}/tests/interface-allocation.c', f'{COMPILER}/src/interface.c', *headers],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', 'tests/interface-allocation.c', f'{COMPILER}/src/source_tree.c', *parser_sources, '-o', f'{BUILD}/interface-allocation-test'])

add('module-allocation-test', [f'{COMPILER}/tests/interface-allocation.c', f'{COMPILER}/src/module.c', *headers],
    [*cc, *cppflags, *cflags, '-DTEST_MODULE', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', 'tests/interface-allocation.c', f'{COMPILER}/src/source_tree.c', *parser_sources, '-o', f'{BUILD}/module-allocation-test'])

add('global-allocation-test', [f'{COMPILER}/tests/global-allocation.c', f'{COMPILER}/src/sema_globals.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', *headers],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', 'tests/global-allocation.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', *parser_sources, '-o', f'{BUILD}/global-allocation-test'])

add('source-failure-test', [f'{COMPILER}/tests/source-failure.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', *headers],
    [*cc, *cppflags, *cflags, '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', 'tests/source-failure.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', *parser_sources, '-o', f'{BUILD}/source-failure-test'])

add('ast-allocation-test', [f'{COMPILER}/tests/ast-allocation.c', f'{COMPILER}/src/ast.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', f'{COMPILER}/src/target.c', *headers],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', 'tests/ast-allocation.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', f'{COMPILER}/src/target.c', *parser_sources, '-o', f'{BUILD}/ast-allocation-test'])

add('module-rewrite-allocation-test', [f'{COMPILER}/tests/module-rewrite-allocation.c', f'{COMPILER}/src/module_rewrite.c', f'{COMPILER}/src/diagnostic.c', *headers],
    [*cc, *cppflags, *cflags, '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections', f'-I{COMPILER}/src', 'tests/module-rewrite-allocation.c', f'{COMPILER}/src/source.c', f'{COMPILER}/src/source_tree.c', f'{COMPILER}/src/diagnostic.c', f'{COMPILER}/src/target.c', *parser_sources, '-o', f'{BUILD}/module-rewrite-allocation-test'])

add('stack-probe-test', [f'{COMPILER}/tests/stack-probe.c', f'{COMPILER}/tests/stack-probe.S', f'{COMPILER}/runtime/windows_stack_probe.S'],
    [*cc, *cppflags, *cflags, 'tests/stack-probe.c', 'tests/stack-probe.S', f'{COMPILER}/runtime/windows_stack_probe.S', '-o', f'{BUILD}/stack-probe-test'])

add('frontend-state-test', [f'{COMPILER}/tests/frontend-state.c', *frontend, *headers],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'{COMPILER}/tests/frontend-state.c', *frontend, '-pthread', '-o', f'{BUILD}/frontend-state-test'])

add('frontend-failure-test', [f'{COMPILER}/tests/frontend-failure.c', f'{COMPILER}/tests/fault-alloc.h', *frontend, f'{COMPILER}/src/ir.c', *headers],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'{COMPILER}/tests/frontend-failure.c', *frontend, f'{COMPILER}/src/ir.c', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/frontend-failure-test'])

add('analysis-cache-test', [f'{COMPILER}/tests/analysis-cache.c', f'{COMPILER}/tests/fault-alloc.h', f'{COMPILER}/src/analysis_cache.c', *frontend, *headers],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'{COMPILER}/tests/analysis-cache.c', f'{COMPILER}/src/analysis_cache.c', *frontend, '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/analysis-cache-test'])

add('codegen-failure-test', [f'{COMPILER}/tests/frontend-failure.c', f'{COMPILER}/tests/fault-alloc.h', *frontend, f'{COMPILER}/src/ir.c', f'{COMPILER}/src/codegen.c', f'{COMPILER}/src/link_elf.c', f'{COMPILER}/src/link_macho.c', f'{COMPILER}/src/link_coff.c', f'{COMPILER}/src/link_wasm.c', *[COMPILER/'src'/n for n in ('codegen_text.c', 'llvm_text.c', 'native_asm.c', 'codegen_wasm.c')], *native_sources, *native_inputs, *headers],
    [*cc, *cppflags, *cflags, '-DTEST_CODEGEN', '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'{COMPILER}/tests/frontend-failure.c', *frontend, f'{COMPILER}/src/ir.c', f'{COMPILER}/src/codegen.c', f'{COMPILER}/src/link_elf.c', f'{COMPILER}/src/link_macho.c', f'{COMPILER}/src/link_coff.c', f'{COMPILER}/src/link_wasm.c', *[COMPILER/'src'/n for n in ('codegen_text.c', 'llvm_text.c', 'native_asm.c', 'codegen_wasm.c')], *native_sources, *native_flags, '-pthread', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/codegen-failure-test'])

add('project-failure-test', [f'{COMPILER}/tests/project-failure.c', f'{COMPILER}/tests/fault-alloc.h', *frontend, f'{COMPILER}/src/module.c', f'{COMPILER}/src/module_rewrite.c', *headers],
    [*cc, *cppflags, *cflags, '-D_POSIX_C_SOURCE=200809L', f'-I{COMPILER}/src', f'{COMPILER}/tests/project-failure.c', *frontend, f'{COMPILER}/src/module.c', f'{COMPILER}/src/module_rewrite.c', '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/project-failure-test'])

add('syntax-cache-test', [f'{COMPILER}/tests/syntax-cache.c', f'{COMPILER}/tests/fault-alloc.h', f'{COMPILER}/src/source_tree.c', *headers],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', 'tests/syntax-cache.c', *parser_sources, '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/syntax-cache-test'])

add('scope-index-test', [f'{COMPILER}/tests/scope-index.c', f'{COMPILER}/tests/fault-alloc.h', *headers],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', 'tests/scope-index.c', f'{COMPILER}/src/source_tree.c', *parser_sources, '-Wl,--wrap=malloc,--wrap=calloc,--wrap=realloc,--wrap=strdup,--wrap=strndup', '-o', f'{BUILD}/scope-index-test'])

add('parser-recovery-test', [COMPILER/'tests/parser-recovery.c', *parser_sources, *headers],
    [*cc, *cflags, '-O1', f'-I{COMPILER}/src', COMPILER/'tests/parser-recovery.c', *parser_sources, '-o', BUILD/'parser-recovery-test'])

add('parser-unit-test', [COMPILER/'tests/parser-unit.c', *parser_sources, *headers],
    [*cc, *cflags, '-O1', f'-I{COMPILER}/src', COMPILER/'tests/parser-unit.c', '-o', BUILD/'parser-unit-test'])
add('parser-snapshot-test', [COMPILER/'tests/parser-snapshot.c', *parser_sources, *headers],
    [*cc, *cflags, '-O1', f'-I{COMPILER}/src', COMPILER/'tests/parser-snapshot.c', '-pthread', '-o', BUILD/'parser-snapshot-test'])

add('unwind-capacity-test', [f'{COMPILER}/tests/unwind-capacity.c', f'{COMPILER}/runtime/reference_support.c'],
    [*cc, *cppflags, *cflags, '-ffreestanding', '-fno-builtin', 'tests/unwind-capacity.c', '-o', f'{BUILD}/unwind-capacity-test'])

add('dyn-per-file', [*sources, *headers, *native_sources, *native_inputs],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', *sources, *native_sources, *native_flags, '-pthread', '-o', BUILD/'dyn-per-file'])

add('build-plan-test', [COMPILER/'tests/build-plan.c', COMPILER/'src/build.c', *headers],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', COMPILER/'tests/build-plan.c', COMPILER/'src/build.c', '-pthread', '-Wl,--wrap=waitpid', '-o', BUILD/'build-plan-test'])
add('interface-test', [COMPILER/'tests/interface-cache.c', *[COMPILER/'src'/n for n in ('interface.c', 'source.c', 'source_tree.c', 'diagnostic.c', 'target.c')], *headers],
    [*cc, *cppflags, *cflags, f'-I{COMPILER}/src', COMPILER/'tests/interface-cache.c', *[COMPILER/'src'/n for n in ('interface.c', 'source.c', 'source_tree.c', 'diagnostic.c', 'target.c')], *parser_sources, '-o', BUILD/'interface-test'])

ALL = ['dynrt_wasi_start.o', 'dynrt_wasi_support.o', 'dynrt_wasm.o', 'dyn', 'dynrt_start.o', 'dynrt_release.o', 'dynrt_support.o', 'dynrt_support_pic.o', 'dynrt_aarch64_support_pic.o', 'dynrt_shared.o', 'dynrt_aarch64_shared.o', 'dynrt_aarch64_start.o', 'dynrt_aarch64_release.o', 'dynrt_aarch64_support.o', 'dynrt_windows_start.o', 'dynrt_windows_support.o', 'dynrt_macos_start.o', 'dynrt_macos_support.o', 'dynrt_windows_shared.o', 'dynrt_macos_shared.o']


ALL += ['dynrt_windows_arm64_start.o', 'dynrt_windows_arm64_shared.o', 'dynrt_windows_arm64_support.o', 'dynrt_macos_x64_start.o', 'dynrt_macos_x64_shared.o', 'dynrt_macos_x64_support.o']
ALL += ['dynrt_riscv64_start.o', 'dynrt_riscv64_release.o', 'dynrt_riscv64_shared.o', 'dynrt_riscv64_support.o', 'dynrt_riscv64_support_pic.o']
HOST = ['dyn-release', *WASM_RUNTIME, *NATIVE_STARTUPS, *NATIVE_SUPPORT]
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
    inputs += [Path(__file__), COMPILER/'justfile']
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
        write_changed(BUILD/'libSystem.tbd', (COMPILER/'runtime/libSystem.tbd').read_text())
        targets = dict.fromkeys(n for t in args.targets for n in (ALL if t == 'all' else HOST if t == 'host' else [t]))
        build_all(targets, max(1, args.jobs))

if __name__ == '__main__':
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as error:
        sys.exit(str(error))
