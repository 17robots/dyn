#!/usr/bin/env python3
"""Bounded math execution on RV32/Thumb hard/soft, debug/release.

Independent host primitive bit goldens and <=1 ULP selected transcendental
samples only: this is no general accuracy claim. External Clang integer
identity hides every numeric operand from Dyn; C needs no float arithmetic
runtime. Reuse the soft fixtures' ELF audits/relocation conversion, without
executing or modifying their tests. ROOT/DYN/CLANG/DYN_QEMU_* and TMPDIR work
as in bare-ssa-soft.py; /tmp/dyn-qemu wrappers are a last-resort discovery.
"""
import ast
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import struct
import subprocess
import tempfile

ROOT = Path(os.environ.get('ROOT', Path(__file__).resolve().parents[1])).resolve()
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))


def helpers(name):
    tree = ast.parse((ROOT/'tests'/name).read_text())
    ns = dict(struct=struct)
    exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, ast.FunctionDef)], type_ignores=[]), name, 'exec'), ns)
    return ns


def bits(x, width=32):
    return struct.unpack('<I' if width == 32 else '<Q', struct.pack('<f' if width == 32 else '<d', x))[0]


def generate():
    lines = ['use "std/math" m', 'use "std/io"',
             'extern fn opaque(x:u64) u64', 'extern fn cpacr() u32',
             'pub fn math_selected_sqrt(x:f64) f64 { return m.sqrt(x) }',
             'fn main() {', 'if cpacr() & 0x00f00000 != 0 { #panic("FPU enabled at entry") }']
    checks = 0

    def raw(x, width=32):
        return f'#bitcast(f{width},#cast(u{width},opaque({x})))'

    def value(x, width=32):
        return raw(bits(x, width), width)

    def flag(condition, label):
        nonlocal checks
        checks += 1
        lines.append(f'if !({condition}) {{ #panic("{checks}: {label}") }}')

    def exact(expr, expected, width=32, tolerance=0):
        lines.append('if true {')
        lines.append(f'b:=#bitcast(u{width},{expr})')
        golden = bits(expected, width)
        if tolerance:
            # Positive finite samples: unsigned bit distance equals ULP distance.
            flag(f'b >= {golden-tolerance} && b <= {golden+tolerance}', expr)
        else:
            flag(f'b == {golden}', expr)
        lines.append('}')

    for width in (32, 64):
        for op, x, expected in [('floor', -1.5, -2.0), ('ceil', -1.5, -1.0),
                                ('trunc', -1.5, -1.0), ('sqrt', 4.0, 2.0)]:
            exact(f'm.{op}({value(x,width)})', expected, width)
        exact(f'm.copysign({value(0.0,width)},{value(-1.0,width)})', -0.0, width)
        exact(f'm.fma({value(1.5,width)},{value(2.0,width)},{value(-2.0,width)})', 1.0, width)
        for op, x in [('sin', .5), ('cos', .5), ('exp', .5), ('log', 2.0)]:
            exact(f'm.{op}({value(x,width)})', getattr(math, op)(x), width, 1)
    exact(f'math_selected_sqrt({value(9,64)})', 3, 64)
    for signed in (False, True):
        t = 'i64' if signed else 'u64'
        lo, hi = (-(1<<63), (1<<63)-1) if signed else (0, (1<<64)-1)
        for a,b in [(hi,1),(lo,1),(hi,hi),(0,0),(-1,-1) if signed else (1,1)]:
            lines.append('if true {')
            lines.append(f'a:=#bitcast({t},opaque({a & ((1<<64)-1)}))\nb:=#bitcast({t},opaque({b & ((1<<64)-1)}))')
            for op, result in [('add',a+b),('sub',a-b),('mul',a*b)]:
                flag(f'm.{op}_overflows(a,b) == {str(not lo<=result<=hi).lower()}', f'{t} {op} overflow')
                lines.append(f's_{op}:{t}=m.saturating_{op}(a,b)')
                lines.append(f'e_{op}:{t}={max(lo,min(hi,result))}')
                flag(f's_{op} == e_{op}', f'{t} saturating {op}')
            flag(f'm.count_ones(a) == {(a & ((1<<64)-1)).bit_count()}', 'popcount64')
            lines.append('}')
    for word in (1, 2, 0x00800000, 0x7f7fffff):
        lines += ['if true {', f'x:={raw(word)}', 'v:=m.vec3_normalize(m.Vec3{x:x})']
        exact('v.x',1.0); exact('v.y',0.0); exact('v.z',0.0)
        exact('m.vec3_length(m.Vec3{x:x})',struct.unpack('<f',struct.pack('<I',word))[0])
        lines.append('}')
    for a,b in [(1,1),(1,3),(2,4),(0x80000001,0x80000001)]:
        # Exact rational midpoint for these same-sign subnormal integer units.
        expected = (a+b)//2 if a<0x80000000 else a
        exact(f'm.rng1f32_center(m.Rng1f32{{min:{raw(a)},max:{raw(b)}}})',struct.unpack('<f',struct.pack('<I',expected))[0])
    for t,lo,hi,mid in [('i64',1<<63,(1<<63)-1,-1),('u64',0,(1<<64)-1,(1<<63)-1)]:
        lines.append(f'mid_{t}:{t}={mid}')
        flag(f'm.rng1{t}_center(m.Rng1{t}{{min:#bitcast({t},opaque({lo})),max:#bitcast({t},opaque({hi}))}}) == mid_{t}','wide midpoint')
    lines += [f'x:={value(2)}', f'z:={value(0)}', f'o:={value(1)}',
              's:=m.mat4_scale(m.Vec3{x:x,y:x,z:x})', 'inv:=m.mat4_inverse(s.value)']
    flag('s.ok && inv.ok','scale inverse')
    for c in range(4):
        for r,field in enumerate('xyzw'):
            exact(f'inv.value.c{c}.{field}', (.5 if c<3 else 1) if c==r else 0)
    lines += ['p:=m.mat4_orthographic(-x,x,-x,x,o,o+x)', 'v:=m.mat4_mul_vec4(p.value,m.Vec4{x:x,y:x,z:-o,w:o})']
    flag('p.ok','projection')
    for field,e in zip('xyzw',[1,1,-1,1]): exact('v.'+field,e)
    lines += ['q:=m.quat_to_mat3(m.Quat{x:z,y:z,z:o,w:z})']
    flag('q.ok','quaternion basis')
    for c in range(3):
        for r,field in enumerate('xyz'): exact(f'q.value.c{c}.{field}',[-1,-1,1][c] if c==r else 0)
    lines += ['if cpacr() & 0x00f00000 != 0 { #panic("FPU enabled on soft Thumb") }',
              '_=io.write_all(io.stdout(),"MATH TARGET PASS\\n")', '}']
    return '\n'.join(lines), checks


def main():
    for command in ([DYN], CLANG):
        if not command or not shutil.which(command[0]):
            print('SKIP math-targets: missing prerequisite '+str(command)); return
    rv, arm = helpers('rv32-soft.py'), helpers('thumb-soft.py')
    source, checks = generate()
    completed = failed = 0
    with tempfile.TemporaryDirectory(prefix='dyn-math-targets-') as tmp:
        work = Path(tmp); project = work/'source'; project.mkdir()
        for arch, variable, program in [('riscv32','DYN_QEMU_RISCV32','qemu-system-riscv32'),('thumbv7em','DYN_QEMU_ARM','qemu-system-arm')]:
            fallback = str(Path('/tmp/dyn-qemu')/program)
            qemu = shlex.split(os.environ.get(variable,'')) or [shutil.which(program) or fallback]
            if not shutil.which(qemu[0]):
                print(f'SKIP math-targets {arch}: missing {qemu}',flush=True); continue
            for soft in (False,True):
                target = arch+'-none'+('-soft' if soft else '')
                thumb = arch == 'thumbv7em'
                # CPACR is meaningful only on soft Thumb; integer-only C otherwise.
                c = '#include <stdint.h>\nuint64_t opaque(uint64_t x){return x;}\nunsigned cpacr(void){return '+('*(volatile unsigned*)0xe000ed88u' if thumb and soft else '0')+';}\n'
                (work/'opaque.c').write_text(c)
                flags = (['--target=arm-none-eabi','-mcpu=cortex-m7','-mthumb', '-mfloat-abi='+('soft' if soft else 'hard')] + ([] if soft else ['-mfpu=fpv5-d16'])) if thumb else ['--target=riscv32-unknown-elf','-mno-relax','-mcmodel=medany','-march='+('rv32im' if soft else 'rv32imafd'),'-mabi='+('ilp32' if soft else 'ilp32d')]
                obj=work/'opaque.o'
                subprocess.run([*CLANG,*flags,'-ffreestanding','-fno-stack-protector','-O2','-c',str(work/'opaque.c'),'-o',str(obj)],check=True,timeout=60)
                if thumb: arm['explicit_arm_addends'](obj)
                (project/'main.dyn').write_text(source)
                for mode in ('debug','release'):
                    try:
                        image=work/'test.elf'
                        env=dict(os.environ); env.pop('DYN_NO_SSA',None)
                        build=subprocess.run([DYN,'build',str(project),'--target',target,'--'+mode,'--no-cache','--quiet','--opt-remarks','--link',str(obj),'--output',str(image)],capture_output=True,text=True,env=env,timeout=180)
                        assert build.returncode==0,build.stdout+build.stderr
                        if mode=='release':
                            assert re.search(r'^remark: math_selected_sqrt: SSA code generation,',build.stdout+build.stderr,re.M),build.stdout+build.stderr
                        audit=(arm if thumb else rv)['check_image'](image) if soft else None
                        board=['-machine','mps2-an500','-semihosting-config','enable=on,target=native'] if thumb else ['-machine','virt','-bios','none',*(['-cpu','sifive-e31'] if soft else [])]
                        proc=subprocess.Popen([*qemu,*board,'-nographic','-kernel',str(image)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,start_new_session=True)
                        try: output,_=proc.communicate(timeout=60)
                        except subprocess.TimeoutExpired:
                            os.killpg(proc.pid,signal.SIGKILL); output,_=proc.communicate(timeout=10)
                            raise AssertionError(f'guest timeout {output[-8192:]!r}')
                        assert proc.returncode==0 and output.replace(b'\r\n',b'\n')==b'MATH TARGET PASS\n',(proc.returncode,output[-8192:])
                        completed+=1
                        print(f'PASS math-targets {target} {mode}: {checks} checks; soft instruction audit={audit}',flush=True)
                    except (AssertionError,subprocess.SubprocessError) as error:
                        failed+=1; print(f'FAIL math-targets {target} {mode}: {error}',flush=True)
    print(f'math-targets: {completed}/8 guests passed, {failed} failed; selected samples only',flush=True)
    if failed: raise SystemExit(1)


if __name__=='__main__': main()
