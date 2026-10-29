#!/usr/bin/env python3
"""Panic: 64 production guests and 48 explicitly backend-only ABI guests.

Production ILP32 descriptors carry 32-bit lengths. The temporary adapter tests
full-u64 backend argument passing, NOT frontend acceptance of wide descriptors.
Its independent C handler checks the pointer/length without reading fake-length
buffers, then calls the real runtime with a valid short message. A returning
handler verifies the mandatory post-call trap in both emitters.
ROOT, BUILD, DYN, CC, COMPILER_CC, CLANG, TMPDIR and DYN_QEMU_ARM/RISCV32 are overrides.
Container prefixes must mount TMPDIR identically and bound their own guests.
All subprocesses are bounded; all generated artifacts are temporary.
"""
import importlib.util
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(os.environ.get('ROOT', Path(__file__).resolve().parents[1])).resolve()
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
DYN = str(Path(os.environ.get('DYN', BUILD/'dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))
# Adapter compilers link compiler objects; guest C helpers still use plain CC.
COMPILER_CC = shlex.split(os.environ.get('COMPILER_CC', os.environ.get('CC', 'cc')))


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT/'tests'/f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


b = module('bare-ssa')
c = module('bare-ssa-checked')
soft = module('bare-ssa-soft')
helpers = module('bare-ssa-cases')
SOURCE = r'''use "std/io"
extern fn opaque() u32
extern fn cpacr() u32
pub fn literal() { #panic("hello") }
pub fn empty() { #panic("") }
pub fn dynamic(s:[]const u8) { #panic(s) }
pub fn sliced(s:[]const u8,a:usize,b:usize) { #panic(s[a..b]) }
pub fn nul() { #panic("a\0b") }
fn message() []const u8 { _=io.write_all(io.stdout(),"EVAL\n")
return "ordered" }
pub fn ordered() { #panic(message()) }
pub fn protected() { defer { _=io.write_all(io.stdout(),"CLEAN\n") }
#panic(message()) }
pub fn caller() { defer { _=io.write_all(io.stdout(),"OUTER\n") }
dynamic("called") }
'''
CASES = [
    ('literal', 'literal()', b'hello\n'),
    ('empty', 'empty()', b''),
    ('dynamic', 'dynamic("dynamic")', b'dynamic\n'),
    ('sliced', 'sliced("!slice?",#cast(usize,opaque()),6)', b'slice\n'),
    ('nul', 'nul()', b'a\0b\n'),
    ('ordered', 'ordered()', b'EVAL\nordered\n'),
    ('protected', 'protected()', b'EVAL\nCLEAN\nordered\n'),
    ('caller', 'caller()', b'OUTER\ncalled\n'),
]
NAMES = [name for name, _, _ in CASES]
FALLBACK = []


def controls():
    lines = [f'remark: {n}: ' + ('tree emitter (paired SSA boundary)' if n in FALLBACK
             else 'SSA code generation, control') for n in NAMES]
    c.check_remarks('\n'.join(lines), 'ssa', NAMES, FALLBACK)
    bad = [('\n'.join(lines[:i]+lines[i+1:]), 'ssa') for i in range(len(lines))]
    bad += [('\n'.join(lines+[f'remark: {n}: '+('SSA code generation, control'
             if n in FALLBACK else 'tree emitter (paired SSA boundary)')]), 'ssa') for n in NAMES]
    bad.append(('\n'.join(lines), 'tree'))
    for log, mode in bad:
        try:
            c.check_remarks(log, mode, NAMES, FALLBACK)
        except AssertionError:
            continue
        raise AssertionError(('lowering negative control accepted', mode, log))
    c.check_remarks('', 'tree', NAMES, FALLBACK)
    soft.controls(['wide'])
    print('PASS panic: 17 production + 2 backend named-remark negative controls', flush=True)


def build_adapter(work):
    if not COMPILER_CC or not shutil.which(COMPILER_CC[0]) or not (BUILD/'obj/release/main.o').exists():
        print('SKIP panic backend adapter: requires CC and release compiler objects', flush=True)
        return None
    work.mkdir()
    (work.parent/'ir_reachability.inc').symlink_to(ROOT/'src/ir_reachability.inc')
    # Copy only the two adapted implementation files and their include entry;
    # production sources and frontend are never modified.
    for path in (ROOT/'src/backend').iterdir():
        if path.name not in ('driver.c', 'ssa.inc', 'compiler.c'):
            (work/path.name).symlink_to(path)
    source = (ROOT/'src/backend/ssa.inc').read_text()
    anchor = 'int32_t panic = ssa_emit(s, SO_PANIC, SC_NONE, data, length, -1, 0, 0);'
    source = soft.replace_once(source, anchor,
        'if (!strcmp(s->f->name,"wide")) length = ssa_load_value(s, ssa_local_address(s, 0), DYN_TYPE_U64, NULL);\n    '+anchor)
    (work/'ssa.inc').write_text(source)
    source = soft.replace_once((ROOT/'src/backend/driver.c').read_text(),
        '{"dyn_panic", "dyn_trace_push"', '{"oraclepanic", "dyn_trace_push"')
    anchor = 'runtime_call(ctx, 0); isa_trap(ctx); reachable=false;'
    source = soft.replace_once(source, anchor,
        'if (!strcmp(f->name,"wide")) isa_load(ctx, isa_argument(ctx,1), ctx->local_offsets[0]);\n      '+anchor)
    (work/'driver.c').write_text(source)
    (work/'compiler.c').write_text((ROOT/'src/backend/compiler.c').read_text())
    compiler = work/'dyn-wide'
    objects = sorted((BUILD/'obj/release').glob('*.o'))
    subprocess.run([*COMPILER_CC, '-std=c11', '-D_POSIX_C_SOURCE=200809L', '-O1',
        '-I'+str(ROOT/'src'), str(work/'compiler.c'),
        *[str(p) for p in objects if p.name != 'compiler.o'], '-pthread', '-o', str(compiler)],
        check=True, timeout=120)
    for runtime in BUILD.glob('dynrt*.o'):
        (work/runtime.name).symlink_to(runtime.resolve())
    return str(compiler)


def object_file(work, code, flags, rv):
    source = work/'oracle.c'
    source.write_text(code)
    obj = work/'oracle.o'
    subprocess.run([*CLANG, *flags, '-ffreestanding', '-fno-stack-protector', '-O2',
                    '-c', str(source), '-o', str(obj)], check=True, timeout=60)
    if not rv:
        b.arm_addends(obj)
    return obj


def pair(project, compiler, target, obj, board, qemu, audit, expected, backend=False):
    results = []
    for mode in ('ssa', 'tree'):
        image = project/(mode+'.elf')
        env = helpers.environment(mode)
        if backend:
            env['DYN_SDK'] = str(ROOT)
        result = subprocess.run([compiler, 'build', str(project), '--release', '--target', target,
            '--no-cache', '--opt-remarks', '--output', str(image), '--link', str(obj)],
            env=env, capture_output=True, text=True, timeout=120)
        log = result.stdout+result.stderr
        assert result.returncode == 0, (target, project.name, mode, log)
        c.check_remarks(log, mode, ['wide'] if backend else NAMES, [] if backend else FALLBACK)
        if audit:
            audit['check_image'](image)
        results.append(helpers.run_guest([*qemu, *board, '-nographic', '-kernel', str(image)]))
    # The shared guest runner normalizes semihosting CRLF to LF, nothing else.
    assert results[0] == results[1] == expected, (target, project.name, expected, results)
    print(f'PASS {target} {"backend-only" if backend else "production"} {project.name}: {expected}', flush=True)


def main():
    controls()
    for label, command in [('DYN', [DYN]), ('CLANG', CLANG)]:
        if not command or not shutil.which(command[0]):
            print(f'SKIP panic: {label} unavailable: {command}', flush=True)
            return
    production = backend = 0
    with tempfile.TemporaryDirectory(prefix='dyn-ssa-panic-') as temporary:
        work = Path(temporary)
        adapter = build_adapter(work/'adapter')
        for target, variable, program, flags, board in b.TARGETS:
            qemu = shlex.split(os.environ.get(variable, '')) or [program]
            if not shutil.which(qemu[0]):
                print(f'SKIP {target} hard/soft guests: unavailable {qemu}; set {variable}', flush=True)
                continue
            for issoft in (False, True):
                t = target+('-soft' if issoft else '')
                rv = t.startswith('riscv')
                ff = flags
                if issoft:
                    ff = ([f.replace('rv32imafd', 'rv32im').replace('ilp32d', 'ilp32') for f in flags]
                          if rv else ['--target=arm-none-eabi', '-mcpu=cortex-m7', '-mthumb', '-mfloat-abi=soft'])
                bb = [*board, *(['-cpu', 'sifive-e31'] if issoft and rv else [])]
                audit = soft.fixture('rv32' if rv else 'thumb')[0] if issoft else None
                tw = work/t
                tw.mkdir()
                cpacr = 'unsigned cpacr(void){'+('return 0;' if rv else 'return *(volatile unsigned*)0xe000ed88;')+'}'
                check = 'if cpacr() & 0x00f00000 != 0 { #panic("FPU enabled") }\n' if issoft and not rv else ''
                obj = object_file(tw, 'unsigned opaque(void){return 1;} '+cpacr, ff, rv)
                for name, body, expected in CASES:
                    project = tw/name
                    project.mkdir()
                    (project/'main.dyn').write_text(SOURCE+'fn main() { '+check+body+' }')
                    pair(project, DYN, t, obj, bb, qemu, audit, (101, expected, b''))
                    production += 2
                if not adapter:
                    continue
                for n in [0, 1, 17, 0x100000001, 0xfedcba9876543210, 'return']:
                    project = tw/('wide-'+str(n))
                    project.mkdir()
                    (project/'main.dyn').write_text('extern fn opaque() u64\nextern fn keep(p:*u64)\nextern fn cpacr() u32\npub fn wide(n:u64) { keep(&n)\n#panic("X") }\nfn main(){'+check+'wide(opaque())}')
                    code = ('typedef unsigned long long U; extern void dyn_panic(const char*,U); '
                            'void keep(U*p){__asm__ volatile(""::"r"(p):"memory");} '
                            'U opaque(void){return '+str(0 if n == 'return' else n)+'ULL;} '+cpacr+
                            ' void oraclepanic(const char*p,U n){')
                    code += ('return;' if n == 'return' else
                             'if(p[0]!=\'X\'||n!='+str(n)+'ULL)dyn_panic("ABI BAD",7);dyn_panic("ABI OK",6);')+'}'
                    obj = object_file(project, code, ff, rv)
                    expected = (102, b'unexpected trap', b'') if n == 'return' else (101, b'ABI OK\n', b'')
                    pair(project, adapter, t, obj, bb, qemu, audit, expected, True)
                    backend += 2
    print(f'{"PASS" if production else "SKIP"} panic: {production}/64 production guests; '
          f'{backend}/48 backend-only full-u64/returning-handler guests; '
          '8 named SSA functions per production SSA image; soft images audited, FPU disabled', flush=True)


if __name__ == '__main__':
    main()
