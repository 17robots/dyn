#!/usr/bin/env python3
"""Production soft SSA: independent Clang ABI and opaque known-IEEE-bit checks.

Reuses the durable aggregate generator (164 functions) and soft fixtures without
editing them. C identity callbacks/byte comparisons test ABI independently;
arithmetic uses known IEEE bits, NOT independent C float arithmetic (soft
compiler-rt is unavailable). Raw arrays retain scalar-word/sret adapters.
ROOT, DYN, CLANG, DYN_QEMU_ARM/RISCV32 and TMPDIR are portable overrides.
Container wrappers must mount TMPDIR identically and bound their own guests.
All subprocesses are bounded; fixtures are removed on success or failure.
"""
import ast
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(os.environ.get('ROOT', Path(__file__).resolve().parents[1])).resolve()
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))
NAMES = 'fastarithmetic32 fastarithmetic64 conversions widen narrow remainder32 remainder64 specialbits32 specialbits64'.split()


def replace_once(text, old, new):
    assert text.count(old) == 1, ('fixture contract changed', old)
    return text.replace(old, new, 1)


def remarks(log, mode, names):
    if mode == 'tree':
        assert 'SSA code generation' not in log, log
    else:
        for name in names:
            messages = re.findall(r'^remark: ' + re.escape(name) + r': (.*)$', log, re.M)
            assert any(m.startswith('SSA code generation,') for m in messages), (name, log)
            assert not any('tree emitter' in m for m in messages), (name, messages)


def controls(names):
    lines = [f'remark: {n}: SSA code generation, control' for n in names]
    remarks('\n'.join(lines), 'ssa', names)
    for i in range(len(names)):
        try:
            remarks('\n'.join(lines[:i] + lines[i+1:]), 'ssa', names)
        except AssertionError:
            continue
        raise AssertionError(('missing remark accepted', names[i]))
    remarks('', 'tree', names)
    try:
        remarks('\n'.join(lines), 'tree', names)
    except AssertionError:
        return
    raise AssertionError('tree accepted SSA remarks')


def aggregate_generator():
    path = ROOT/'tests/bare-ssa-aggregate-calls.py'
    text = path.read_text()
    # Adapt the generator, not its emitted machine code. Exact anchors fail
    # loudly if its contract changes. No C floating-point operations remain.
    for old, new in [
        ('x.{fields[0][0]}+=1;', ''), ('x.a+=1;', ''),
        ('a.{f}!=x.{f} || r.{f}!=x.{f}+{2 if j==0 else 0} || q.{f}!=x.{f}+{1 if j==0 else 0}',
         '!EQ(a.{f},x.{f}) || !EQ(r.{f},x.{f}) || !EQ(q.{f},x.{f})'),
        ('r.a!=1', '!EQ(r.a,0)'), ('r.a!=4.5', '!EQ(r.a,x.a)'),
    ]:
        text = replace_once(text, old, new)
    text = replace_once(text, 'process.communicate()', 'process.communicate(timeout=10)')
    ns = {'__file__': str(path), '__name__': 'soft_aggregate_generator'}
    exec(compile(text, str(path), 'exec'), ns)
    ns['c'] = '#define EQ(a,b) ({ __typeof__(a) aa=(a),bb=(b); unsigned char *ap=(void*)&aa,*bp=(void*)&bb; int eq=1; for(unsigned i=0;i<sizeof(aa);i++) if(ap[i]!=bp[i])eq=0;eq; })\n' + ns['c']
    assert len(ns['names']) == len(set(ns['names'])) == 164
    return ns


def fixture(name):
    """Execute definitions/generation only; defer the standalone test body."""
    path = ROOT/'tests'/f'{name}-soft.py'
    text = path.read_text()
    text = replace_once(text, 'ROOT = Path(__file__).resolve().parents[1]', f'ROOT = Path({str(ROOT)!r})')
    # Tighten the existing successful-guest assertion to exact combined output.
    marker = 'RV32' if name == 'rv32' else 'THUMB'
    text = replace_once(text, f"b'{marker} SOFT PASS' in output", f"output.replace(b'\\r\\n', b'\\n') == b'{marker} SOFT PASS\\n'")
    text = text.replace('guest.communicate()', 'guest.communicate(timeout=10)')
    module = ast.parse(text, str(path))
    boundary = next(i for i, node in enumerate(module.body) if isinstance(node, ast.With))
    ns = {'__file__': str(path), '__name__': 'soft_fixture'}
    exec(compile(ast.Module(body=module.body[:boundary], type_ignores=[]), str(path), 'exec'), ns)
    return ns, compile(ast.Module(body=module.body[boundary:], type_ignores=[]), str(path), 'exec')


def extend(ns):
    D, B, C = ns['D'], ns['B'], ns['C']
    # Preserve the opaque inputs, checking exact representation of every
    # floating result as well as the existing exact integer results.
    generated = '\n'.join(D)
    for old, new in [
        ('#cast(f32,x) != -7.0', '#bitcast(u32,#cast(f32,x)) != 0xc0e00000'),
        ('#cast(f64,x) != -7.0', '#bitcast(u64,#cast(f64,x)) != 0xc01c000000000000'),
        ('#cast(f32,y) != 9.0', '#bitcast(u32,#cast(f32,y)) != 0x41100000'),
        ('#cast(f64,y) != 9.0', '#bitcast(u64,#cast(f64,y)) != 0x4022000000000000'),
        ('#cast(f64,a) != -7.5', '#bitcast(u64,#cast(f64,a)) != 0xc01e000000000000'),
        ('#cast(f32,b) != 9.5', '#bitcast(u32,#cast(f32,b)) != 0x41180000'),
    ]:
        generated = replace_once(generated, old, new)
    D[:] = generated.split('\n')
    for width,ct,bits in [(32,'float','0xffc12345U'),(64,'double','0xfff8123456789abcULL')]:
        D += [f'fn fastarithmetic{width}(op:i32,x:u{width},y:u{width}) u{width} {{ a:=#bitcast(f{width},x) b:=#bitcast(f{width},y)']
        D += [f'if op == {i} {{ return #bitcast(u{width},{expr}) }}' for i,expr in enumerate(['a+b','a-b','a*b','a/b','a%b'])]
        D += ['if a != b && !(a == b) && !(a < b) && !(a <= b) && !(a > b) && !(a >= b) { return 1 } return 0 }']
        B += [f'if arithmetic_check{width}(&fastarithmetic{width}) != 0 {{ #panic("SSA arithmetic") }}']
        D += [f'fn specialbits{width}(x:f{width}) f{width} {{ return x }}',
              f'fn remainder{width}(x:f{width},y:f{width}) f{width} {{ return x%y }}',
              f'extern fn extra{width}(p:*fn(f{width}) f{width},r:*fn(f{width},f{width}) f{width}) i32']
        union='Fbits' if width==32 else 'Dbits'
        sign='0x80000000U' if width==32 else '0x8000000000000000ULL'
        C += [f'int extra{width}({ct} (*p)({ct}),{ct} (*r)({ct},{ct})) {{ {union} x={{.u={bits}}}, z={{.u={sign}}}; return ({union}){{.f=p(x.f)}}.u==x.u && ({union}){{.f=r(z.f,2)}}.u==z.u && ({union}){{.f=r(-7,2)}}.u==({union}){{.f=-1}}.u; }}']
        B += [f'if extra{width}(&specialbits{width},&remainder{width}) != 1 {{ #panic("specialbits/remainder") }}']
    ns["D"] = [line.replace("fn ", "pub fn ", 1) if line.startswith("fn ") else line for line in D]


def arithmetic(ns, body, lowering):
    def run(command, **kwargs):
        if command[0] == DYN:
            result = subprocess.run([*command, '--opt-remarks'], check=True,
                                    timeout=120, capture_output=True, **kwargs)
            log = (result.stdout + result.stderr).decode()
            if '--release' in command:
                remarks(log, lowering, NAMES)
            elif lowering == 'tree':
                remarks(log, lowering, NAMES)
            return result
        return subprocess.run(command, check=True, timeout=120, **kwargs)
    ns['run'] = run
    exec(body, ns)


def aggregates(g, ns, target, flags, board, qemu):
    with tempfile.TemporaryDirectory(prefix='dyn-ssa-soft-aggregate-') as tmp:
        work = Path(tmp)
        source = g['source']
        c = g['c']
        if target.startswith('thumb'):
            # Verify CP10/11 remain disabled around the entire oracle.
            c += '\nunsigned cpacr(void){return *(volatile unsigned*)0xe000ed88u;}\n'
            source = 'extern fn cpacr() u32\n' + source
            source = replace_once(source, 'n:=oracle()', 'if cpacr() & 0x00f00000 != 0 { #panic("FPU entry") } n:=oracle() if cpacr() & 0x00f00000 != 0 { #panic("FPU exit") }')
        project = work/'source'
        project.mkdir()
        (project/'main.dyn').write_text(source)
        (work/'oracle.c').write_text(c)
        obj = work/'oracle.o'
        subprocess.run([*CLANG, *flags, '-ffreestanding', '-fno-stack-protector',
                        '-O2', '-c', str(work/'oracle.c'), '-o', str(obj)], check=True, timeout=60)
        if target.startswith('thumb'):
            ns['explicit_arm_addends'](obj)
        for mode in ('ssa', 'tree'):
            env = dict(os.environ)
            env.pop('DYN_NO_SSA', None)
            if mode == 'tree':
                env['DYN_NO_SSA'] = '1'
            image = work/f'{mode}.elf'
            result = subprocess.run([DYN, 'build', str(project), '--release', '--target', target,
                '--no-cache', '--opt-remarks', '--link', str(obj), '--output', str(image)],
                env=env, capture_output=True, text=True, timeout=120)
            assert result.returncode == 0, result.stdout + result.stderr
            remarks(result.stdout + result.stderr, mode, g['names'])
            count = ns['check_image'](image)
            actual = g['run_guest']([*qemu, *board, '-nographic', '-kernel', str(image)])
            assert actual == (0, b'ABI OK\n', b''), (target, mode, actual)
            print(f'PASS {target} {mode}: 164 ABI functions, exact output, {count} no-FP instructions', flush=True)


def main():
    g = aggregate_generator()
    controls(g['names'])
    controls(NAMES)
    print('PASS soft SSA: 173 missing-remark and 2 tree-remark controls', flush=True)
    for label, command in [('DYN', [DYN]), ('CLANG', CLANG)]:
        if not command or not shutil.which(command[0]):
            print(f'SKIP bare-ssa-soft: {label} unavailable: {command}', flush=True)
            return
    completed = 0
    for target, variable, program, flags, board in g['b'].TARGETS:
        qemu = shlex.split(os.environ.get(variable, '')) or [program]
        if not shutil.which(qemu[0]):
            print(f'SKIP {target}-soft: unavailable {qemu}; set {variable}', flush=True)
            continue
        rv = target.startswith('riscv')
        flags = ([f.replace('rv32imafd', 'rv32im').replace('ilp32d', 'ilp32') for f in flags]
                 if rv else ['--target=arm-none-eabi', '-mcpu=cortex-m7', '-mthumb', '-mfloat-abi=soft'])
        board = [*board, *(['-cpu', 'sifive-e31'] if rv else [])]
        ns, body = fixture('rv32' if rv else 'thumb')
        extend(ns)
        aggregates(g, ns, target+'-soft', flags, board, qemu)
        for mode in ('ssa', 'tree'):
            os.environ.pop('DYN_NO_SSA', None)
            if mode == 'tree':
                os.environ['DYN_NO_SSA'] = '1'
            print(f'RUN {target}-soft {mode}: debug/release known-bit oracle', flush=True)
            arithmetic(ns, body, mode)
        completed += 1
    if completed:
        print(f'PASS bare-ssa-soft: {completed}/2 targets; per target 2 aggregate + 4 arithmetic guests; '
              'Thumb adds 2 checked-panic guests (4 cleanups each); 164 aggregate and 9 arithmetic SSA names', flush=True)
    else:
        print('SKIP bare-ssa-soft: no QEMU targets executed', flush=True)


if __name__ == '__main__':
    main()
