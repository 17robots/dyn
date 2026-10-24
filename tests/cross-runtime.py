#!/usr/bin/env python3
"""Target-tool-free runtime assembly and actual memory/atomic ABI execution."""
import importlib.util
import os
from pathlib import Path
import platform
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native_runtime', ROOT / 'tools/native-runtime.py')
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)


def run(command, **kwargs):
    result = subprocess.run(list(map(str, command)), text=True, capture_output=True,
                            timeout=90, **kwargs)
    assert result.returncode == 0, (command, result.stdout, result.stderr)
    return result


NAMES = ('dynrt_start.o', 'dynrt_release.o', 'dynrt_shared.o',
         'dynrt_aarch64_start.o', 'dynrt_aarch64_release.o', 'dynrt_aarch64_shared.o',
         'dynrt_riscv64_start.o', 'dynrt_riscv64_release.o', 'dynrt_riscv64_shared.o',
         'dynrt_riscv64_none_start.o', 'dynrt_riscv64_none_release.o',
         'dynrt_riscv32_none_start.o', 'dynrt_riscv32_none_release.o',
         'dynrt_thumbv7em_none_start.o', 'dynrt_thumbv7em_none_release.o',
         'dynrt_windows_start.o', 'dynrt_windows_shared.o',
         'dynrt_macos_start.o', 'dynrt_macos_shared.o',
         'dynrt_macos_x64_start.o', 'dynrt_macos_x64_shared.o',
         'dynrt_windows_arm64_start.o', 'dynrt_windows_arm64_shared.o')

SOURCE = 'use "std/io"\nuse "std/thread"\nuse "std/mem" mem\nuse "std/errors" errors\nuse "std/sync"\nfn remainder(x: f64, y: f64) f64 { return x % y }\nfn remainder32(x: f32, y: f32) f32 { return x % y }\nstruct Context { count: sync.AtomicU64 }\nfn worker(pointer: rawptr) isize {\n  context := #cast(*Context, pointer)\n  defer { _ = sync.fetch_add_u64(&context.count, 1) }\n  for i in 0..1000 { _ = sync.fetch_add_u64(&context.count, 1) }\n  return 0\n}\nfn main() {\n  arena:mem.Arena\n  defer { mem.arena_release(&arena) }\n  context := Context{}\n  spawned:=thread.spawn_with_size(&arena,65536,&worker,#cast(rawptr,&context))\n  if !spawned.ok { #panic("spawn") } active:=spawned.value\n  if !thread.join(active).ok || sync.load_u64(&context.count) != 1001 { #panic("join") }\n\n  if remainder(5.5, 2.0) != 1.5 || remainder(-5.5, 2.0) != -1.5 { #panic("fmod") }\n  if remainder32(5.5, 2.0) != 1.5 { #panic("fmodf") }\n  if (#bitcast(u64, remainder(-4.0, 2.0))) != 0x8000000000000000 { #panic("negative zero") }\n  _ = io.println(io.stdout(), "cross runtime ready")\n}\n'
PANIC = '''use "std/io"
fn child(value: f64) {
  defer {
    if value != 2.25 { #panic("lost nonvolatile floating register") }
    _ = io.println(io.stdout(), "inner cleanup")
  }
  #panic("cross runtime panic")
}
fn main() {
  defer { _ = io.println(io.stdout(), "outer cleanup") }
  child(2.25)
}
'''

HARNESS = r'''
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#ifdef WINDOWS_ABI
#define ABI __attribute__((ms_abi))
#else
#define ABI
#endif
extern ABI void *rt_copy(void *, const void *, size_t);
extern ABI void *rt_move(void *, const void *, size_t);
extern ABI void *rt_fill(void *, int, size_t);
static unsigned char bytes[1100], expected[1100], snapshot[1100];
static void check(void) {
    for (size_t i = 0; i < sizeof(bytes); ++i)
        if (bytes[i] != expected[i]) abort();
}
int main(void) {
    if (rt_copy(NULL, NULL, 0) || rt_move(NULL, NULL, 0) || rt_fill(NULL, 1, 0)) abort();
    for (size_t length = 0; length <= 1024; ++length) {
        for (size_t i = 0; i < sizeof(bytes); ++i) bytes[i] = expected[i] = (unsigned char)(i * 13);
        for (size_t i = 0; i < length; ++i) expected[i + 3] = 0xa7;
        if (rt_fill(bytes + 3, 0x1234a7, length) != bytes + 3) abort();
        check();
        for (int direction = 0; direction < 2; ++direction) {
            for (size_t distance = 0; distance <= 17; ++distance) {
                for (size_t i = 0; i < sizeof(bytes); ++i)
                    bytes[i] = expected[i] = snapshot[i] = (unsigned char)(i * 7 + length);
                size_t src = direction ? 3 : 3 + distance;
                size_t dst = direction ? 3 + distance : 3;
                for (size_t i = 0; i < length; ++i) expected[dst + i] = snapshot[src + i];
                if (rt_move(bytes + dst, bytes + src, length) != bytes + dst) abort();
                check();
            }
        }
        for (size_t i = 0; i < sizeof(bytes); ++i) bytes[i] = expected[i] = (unsigned char)i;
        for (size_t i = 0; i < length; ++i) expected[i + 3] = snapshot[i + 1];
        if (rt_copy(bytes + 3, snapshot + 1, length) != bytes + 3) abort();
        check();
    }
    puts("PASS memory counts, alignment, overlap, return pointers, ABI");
    return 0;
}
'''

with tempfile.TemporaryDirectory(prefix='dyn-cross-runtime-') as temporary:
    root = Path(temporary)
    empty = root / 'empty'; empty.mkdir()
    for name in NAMES:
        output = root / name
        run([sys.executable, ROOT / 'tools/native-runtime.py', '--output', output],
            env=dict(os.environ, PATH=str(empty)))
        original = output.read_bytes()
        run([sys.executable, ROOT / 'tools/native-runtime.py', '--output', output],
            env=dict(os.environ, PATH=str(empty)))
        assert output.read_bytes() == original, ('nondeterministic runtime', name)
        if 'windows' in name:
            assert struct.unpack_from('<H', original)[0] == (0xaa64 if 'arm64' in name else 0x8664)
        elif 'macos' in name:
            assert struct.unpack_from('<II', original) == (0xfeedfacf, 0x1000007 if 'x64' in name else 0x100000c)
        else:
            assert original[:4] == b'\x7fELF'
            assert struct.unpack_from('<H', original, 18)[0] == (243 if 'riscv' in name else 40 if 'thumb' in name else 183 if 'aarch64' in name else 62)
    print('PASS all native startup/shared runtime objects with empty PATH; reproducible bytes')

    if platform.system() == 'Linux' and platform.machine().lower() in ('x86_64', 'amd64'):
        cc = shlex.split(os.environ.get('CC', 'cc'))
        for windows in (False, True):
            assembler = runtime.Assembler('x86_64-linux').assemble(
                ROOT / 'runtime/native_memory_x86_64.S', {'DYN_WINDOWS'} if windows else set())
            # Rename only the three public entry symbols; the fixture must not
            # override libc or let the C compiler replace its calls as builtins.
            aliases = {'memcpy': 'rt_copy', 'memmove': 'rt_move', 'memset': 'rt_fill'}
            assembler.symbols = {aliases.get(k, k): v for k, v in assembler.symbols.items()}
            assembler.globals = {aliases.get(k, k) for k in assembler.globals}
            assembler.hidden = {aliases.get(k, k) for k in assembler.hidden}
            obj = root / ('windows-memory.o' if windows else 'sysv-memory.o')
            obj.write_bytes(assembler.object())
            source = root / 'memory.c'; source.write_text(HARNESS)
            executable = root / ('windows-memory' if windows else 'sysv-memory')
            run([*cc, '-O2', '-fno-builtin', *(['-DWINDOWS_ABI'] if windows else []),
                 source, obj, '-o', executable])
            run([executable])
        print('PASS executed x86-64 SysV and Windows memory ABIs (unaligned/overlapping/zero/full-byte values)')
    else:
        print('SKIP dual-x86 memory harness: requires x86-64 Linux')

    compiler = Path(os.environ.get('DYN', ROOT / 'build' / ('dyn.exe' if os.name == 'nt' else 'dyn'))).resolve()
    if compiler.exists():
        # Link the objects just generated above, not whichever startup objects
        # happen to be installed beside the supplied compiler.
        if os.environ.get('DYN_TEST_INSTALLED') != '1':
            original = compiler
            compiler = root / ('dyn.exe' if os.name == 'nt' else 'dyn')
            shutil.copy2(original, compiler)
            for name in ('dynrt_support.o', 'dynrt_support_pic.o',
                         'dynrt_aarch64_support.o', 'dynrt_aarch64_support_pic.o',
                         'dynrt_riscv64_support.o', 'dynrt_riscv64_support_pic.o', 'dynrt_riscv64_none_support.o', 'dynrt_riscv32_none_support.o', 'dynrt_thumbv7em_none_support.o',
                         'dynrt_windows_support.o', 'dynrt_macos_support.o',
                         'dynrt_macos_x64_support.o', 'dynrt_windows_arm64_support.o', 'libSystem.tbd'):
                candidate = original.parent / name
                if not candidate.exists():
                    candidate = original.parent.parent / 'lib/dyn' / name
                assert candidate.exists(), ('missing portable runtime', candidate)
                shutil.copy2(candidate, root / name)
        project = root / 'project'; project.mkdir()
        source = project / 'main.dyn'
        success = SOURCE
        panic = PANIC
        environment = dict(os.environ, DYN_SDK=str(ROOT), DYN_LINKER='builtin', PATH=str(empty))
        if os.environ.get('DYN_TEST_INSTALLED') == '1':
            environment.pop('DYN_SDK', None)
        if os.name == 'nt':
            environment['PATH'] = os.environ.get('PATH', '')
        machine = platform.machine().lower()
        host_target = (('aarch64-windows' if machine in ('aarch64', 'arm64') else 'x86_64-windows') if os.name == 'nt' else
                       ('aarch64-macos' if machine in ('aarch64', 'arm64') else 'x86_64-macos') if platform.system() == 'Darwin' else
                       'riscv64-linux' if machine == 'riscv64' else 'aarch64-linux' if machine in ('aarch64', 'arm64') else 'x86_64-linux')
        qemu = shutil.which('qemu-aarch64') if platform.system() == 'Linux' else None
        rv_qemu = shutil.which('qemu-riscv64') if platform.system() == 'Linux' else None
        for target in ('riscv64-linux', 'x86_64-linux', 'aarch64-linux', 'aarch64-macos', 'x86_64-macos', 'x86_64-windows', 'aarch64-windows'):
            for mode in ('debug', 'release'):
                source.write_text('pub fn calculate(value: f64) f64 { return value % 2.0 }\n')
                shared = root / (target + '-' + mode + '-shared')
                run([compiler, 'build', project, '--target', target, '--backend', 'native',
                     '--' + mode, '--shared', '--no-cache', '--jobs', '1', '--output', shared], env=environment)
                for name, text in (('success', success), ('panic', panic)):
                    source.write_text(text)
                    output = root / (target + '-' + mode + '-' + name + ('.exe' if target.endswith('windows') else ''))
                    run([compiler, 'build', project, '--target', target, '--backend', 'native',
                         '--' + mode, '--no-cache', '--jobs', '1', '--output', output], env=environment)
                    runner = [] if target == host_target else [rv_qemu] if target == 'riscv64-linux' and rv_qemu else [qemu] if target == 'aarch64-linux' and qemu else None
                    if runner is not None:
                        result = subprocess.run([*runner, str(output)], text=True, capture_output=True, timeout=20)
                        assert result.returncode == (101 if name == 'panic' else 0), (target, mode, name, result)
                        if name == 'panic':
                            assert result.stdout.splitlines() == ['inner cleanup', 'outer cleanup'], result
                            assert 'cross runtime panic' in result.stderr, result
                        else:
                            assert result.stdout == 'cross runtime ready\n', result
        print('PASS all seven native targets link debug/release with empty PATH; host and available ARM/RV emulators execute threads/atomics/fmod/panic/defer')
    else:
        print('SKIP cross-link execution: build compiler or set DYN')

    # Unsupported source must fail before replacing a good output object.
    malformed = root / 'unsupported.S'; malformed.write_text('.text\nunsupported_instruction\n')
    try:
        runtime.Assembler('x86_64-linux').assemble(malformed)
    except ValueError as error:
        assert 'unsupported' in str(error)
    else:
        raise AssertionError('unknown assembler instruction accepted')
print('PASS independent native runtime generator')
