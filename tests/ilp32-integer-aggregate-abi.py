#!/usr/bin/env python3
"""RV32/Thumb integer and composite C ABI boundaries, independent clang oracle.

Checks incoming/outgoing direct/indirect calls, full-width scalar words,
aggregate copies/returns, register exhaustion, alignment and prior VFP spills.
DYN, CLANG, DYN_QEMU_RISCV32 and DYN_QEMU_ARM follow the float/HFA tests.
Artifacts live under build/ilp32-integer-aggregate-abi for container mounts.
"""
import os
from pathlib import Path
import shlex
import shutil
import signal
import struct
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
WORK = ROOT/'build/ilp32-integer-aggregate-abi'
WORK.mkdir(parents=True, exist_ok=True)

def explicit_arm_addends(path):
    """Bridge clang REL to the built-in linker's explicit-addend dialect.

    Only relocation metadata changes; clang's argument/result instructions
    remain untouched. EHABI unwind indexes are unused by this bare-metal test.
    Dyn's Thumb branch relocations already subtract the PC bias themselves.
    """
    data = bytearray(path.read_bytes())
    shoff, = struct.unpack_from('<I', data, 32)
    entsize, count = struct.unpack_from('<HH', data, 46)
    sections = [list(struct.unpack_from('<10I', data, shoff+i*entsize)) for i in range(count)]
    for section in sections:
        if section[1] == 0x70000001:  # SHT_ARM_EXIDX
            section[2] = 0
            section[5] = 0
        if section[1] != 9:  # SHT_REL
            continue
        target = sections[section[7]]
        converted = bytearray()
        if target[1] != 0x70000001:
            for at in range(section[4], section[4]+section[5], 8):
                offset, info = struct.unpack_from('<II', data, at)
                kind = info & 255
                loc = target[4]+offset
                if kind in (2, 3):
                    addend, = struct.unpack_from('<i', data, loc)
                elif kind in (10, 30):
                    hi, lo = struct.unpack_from('<HH', data, loc)
                    sign = (hi >> 10) & 1
                    value = (sign<<24) | ((1 ^ ((lo>>13)&1) ^ sign)<<23) | ((1 ^ ((lo>>11)&1) ^ sign)<<22) | ((hi&1023)<<12) | ((lo&2047)<<1)
                    addend = value - (1<<25) if sign else value
                    addend += 4
                elif kind in (47, 48):
                    hi, lo = struct.unpack_from('<HH', data, loc)
                    addend = ((hi&15)<<12) | (((hi>>10)&1)<<11) | (((lo>>12)&7)<<8) | (lo&255)
                    if kind == 48:
                        addend <<= 16
                    if addend >= 1<<31:
                        addend -= 1<<32
                else:
                    raise AssertionError(f'unhandled clang ARM relocation {kind}')
                converted += struct.pack('<IIi', offset, info, addend)
        data += bytes((-len(data)) % 4)
        section[1], section[4], section[5], section[9] = 4, len(data), len(converted), 12
        data += converted
    for i, section in enumerate(sections):
        struct.pack_into('<10I', data, shoff+i*entsize, *section)
    path.write_bytes(data)


CT = {'i32':'int', 'i64':'long long', 'u64':'unsigned long long', 'f64':'double'}



def helper_boundaries():
    """Exercise real static ABI helpers, including frontend-inexpressible varargs."""
    harness = WORK/'helper.c'
    harness.write_text('#include "'+str(ROOT/'src/backend/driver.c')+'"\n'+r"""
#include <assert.h>
#include <limits.h>
int main(void) {
  static BackendContext ctx;
  DynIrField field = {.type=DYN_TYPE_U64};
  DynIrStruct records[] = {
    {.field_count=1,.size=8,.alignment=8},
    {.size=2048,.alignment=4},
    {.size=16,.alignment=8}
  };
  DynIrProgram ir = {.fields=&field,.field_count=1,.structs=records,.struct_count=3};
  AbiPart parts[513], saved[513];
  unsigned gp,fp,n; bool indirect;
  backend_pointer_bits=32; ctx.rv32=true; ctx.rv_variadic=true;
  for (unsigned prefix=1;prefix<=7;prefix+=2) {
    gp=prefix; fp=0;
    assert(abi_assign(&ctx,&ir,DYN_TYPE_STRUCT_BASE,&gp,&fp,parts,&n,512,&indirect));
    assert(n==2 && !indirect);
    assert(parts[0].cls==(prefix==7?-1:(int)prefix+1));
    assert(parts[1].cls==(prefix==7?-1:(int)prefix+2));
    assert(abi_assign(&ctx,&ir,DYN_TYPE_I32,&gp,&fp,parts+2,&n,510,&indirect));
    assert(parts[2].cls==(prefix>=5?-1:(int)prefix+3));
    if (prefix==7) {
      unsigned cursor=4;
      assert(stack_slot(&ctx,&parts[0],&cursor)==8);
      assert(stack_slot(&ctx,&parts[1],&cursor)==12);
      assert(stack_slot(&ctx,&parts[2],&cursor)==16);
    }
  }
  /* Named align8 aggregates retain the permitted a7/stack split. */
  ctx.rv_variadic=false; gp=7; fp=0;
  assert(abi_assign(&ctx,&ir,DYN_TYPE_STRUCT_BASE,&gp,&fp,parts,&n,512,&indirect));
  assert(parts[0].cls==7 && parts[1].cls==-1);
  /* Every dispatch variant: zero capacity scalar/indirect, and short descriptor. */
  for (unsigned target=0;target<7;++target) {
    memset(&ctx,0,sizeof(ctx));
    ctx.rv32=target==0; ctx.t32=target==1; ctx.rv64=target==2;
    ctx.win64=target==3; ctx.a64=target==4 || target==5;
    ctx.winarm_variadic=target==5;
    backend_pointer_bits=target<2?32:64;
    DynType types[]={DYN_TYPE_I32,DYN_TYPE_STRUCT_BASE+1,DYN_TYPE_STRING,DYN_TYPE_ANY};
    for (unsigned t=0;t<4;++t) {
      memset(parts,0xa5,sizeof(parts)); memcpy(saved,parts,sizeof(parts));
      gp=fp=0;
      assert(!abi_assign(&ctx,&ir,types[t],&gp,&fp,parts,&n,0,&indirect));
      assert(!memcmp(saved,parts,sizeof(parts)));
    }
    gp=fp=0;
    assert(!abi_assign(&ctx,&ir,DYN_TYPE_STRING,&gp,&fp,parts,&n,1,&indirect));
    assert(!memcmp(saved,parts,sizeof(parts)));
    gp=fp=0;
    assert(abi_assign(&ctx,&ir,DYN_TYPE_STRING,&gp,&fp,parts,&n,2,&indirect) && n==2);
  }
  for (unsigned thumb=0;thumb<2;++thumb) {
    memset(&ctx,0,sizeof(ctx)); ctx.t32=thumb;ctx.rv32=!thumb;
    backend_pointer_bits=32;
    CallPlan plan; unsigned total=0;gp=fp=0;
    if (thumb) {
      assert(plan_argument(&ctx,&ir,&plan,0,DYN_TYPE_STRUCT_BASE+1,&gp,&fp,&total));
    } else {
      for (unsigned i=0;i<512;++i)
        assert(plan_argument(&ctx,&ir,&plan,i,DYN_TYPE_I32,&gp,&fp,&total));
    }
    assert(total==512);
    CallPlan before=plan;
    assert(!plan_argument(&ctx,&ir,&plan,512,DYN_TYPE_I32,&gp,&fp,&total));
    assert(total==512 && !memcmp(before.parts,plan.parts,sizeof(plan.parts)));
    assert(!plan_argument(&ctx,&ir,&plan,512,DYN_TYPE_STRUCT_BASE+2,&gp,&fp,&total));
    assert(total==512 && !memcmp(before.parts,plan.parts,sizeof(plan.parts)));
    total=UINT_MAX;
    assert(!plan_argument(&ctx,&ir,&plan,0,DYN_TYPE_I32,&gp,&fp,&total));
    assert(total==UINT_MAX);
  }
  puts("PASS ABI helper alignment/capacity boundaries (7 dispatch variants)");
}
""")
    for opt in ('-O0','-O2'):
        exe = WORK/('helper'+opt)
        subprocess.run([*shlex.split(os.environ.get('CC','cc')), '-std=c11','-D_GNU_SOURCE','-DDYN_BACKEND_EMBEDDED',opt,
                        '-ffunction-sections','-fdata-sections','-I'+str(ROOT/'src'),
                        str(harness),str(ROOT/'src/ast.c'),'-Wl,--gc-sections','-lm','-o',str(exe)],check=True)
        subprocess.run([str(exe)],check=True)


def compiler_boundaries():
    """Exact capacity succeeds; the next part produces a normal diagnostic."""
    for target, thumb in (('riscv32-none',False),('thumbv7em-none',True)):
        work=WORK/target/'capacity'
        work.mkdir(parents=True,exist_ok=True)
        for extra in (False,True):
            if thumb:
                decl='struct Big { v:[2048]u8 }\n'
                params=['x:Big']
                args=['x']
                init='x:Big = Big{v:['+','.join(['0']*2048)+']}'
            else:
                decl=''
                params=['x:[512]i32']
                args=['x']
                init='x:[512]i32 = ['+','.join(['0']*512)+']'
            if extra:
                params+=['tail:i32']; args+=['19']
            (work/'main.dyn').write_text(decl+'fn take('+','.join(params)+') i32 { return 1 }\n'
                +'fn main() { '+init+'\n_ = take('+','.join(args)+') }\n')
            for release in (False,True):
                result=subprocess.run([DYN,'build',str(work),'--target',target,'--no-cache',
                    '--quiet','--output',str(work/'test.elf')]+(['--release'] if release else []),
                    capture_output=True,text=True,timeout=120)
                if extra:
                    assert result.returncode>0 and 'error: native emission failed' in result.stderr, result
                else:
                    assert result.returncode==0, result.stderr
            print(f'PASS {target} capacity {512+extra}: '+('diagnostic' if extra else 'accepted'),flush=True)
    # This frontend limit is explicit, never a silently skipped ABI regression.
    work=WORK/'variadic-frontend'
    work.mkdir(exist_ok=True)
    (work/'main.dyn').write_text('struct A { x:u64 }\nextern fn v(n:i32,...) i32\n'
                               'fn main() { a:=A{x:1}\n_ = v(1,a) }\n')
    result=subprocess.run([DYN,'build',str(work),'--target','riscv32-none','--no-cache','--quiet'],
                          capture_output=True,text=True,timeout=120)
    assert result.returncode>0 and 'C variadic argument requires integer, float, or pointer' in result.stderr, result.stderr
    print('LIMIT: frontend rejects unnamed C aggregates; real ABI helper tested directly',flush=True)


def suite(target, batch):
    thumb = target == 'thumb'
    work = WORK/target/str(batch)
    source = work/'source'
    source.mkdir(parents=True, exist_ok=True)
    c = ['#include <stdarg.h>',
         # Clang emits these helpers for large byte-aligned structs.
         'void __aeabi_memclr(void *p, unsigned n) { volatile unsigned char *q=p; while(n--) *q++=0; }',
         'void __aeabi_memcpy(void *d, const void *s, unsigned n) { volatile unsigned char *q=d; const volatile unsigned char *p=s; while(n--) *q++=*p++; }']
    for alignment in (4,8):
        c += [f'void __aeabi_memclr{alignment}(void *p, unsigned n) {{ __aeabi_memclr(p,n); }}',
              f'void __aeabi_memcpy{alignment}(void *d, const void *s, unsigned n) {{ __aeabi_memcpy(d,s,n); }}']
    dyn = ['use "std/io"']
    body = []
    checks = 0
    # Byte tails prove that chunk loads/stores do not drop partial words.
    cases = [('I64','long long','i64','-81985529216486895', [('', '-81985529216486895')]),
             ('U64','unsigned long long','u64','18364758544493064720', [('', '18364758544493064720')])]
    for n in (1,2,3,5,8,12,16,64,68,80):
        name = f'B{n}'
        c.append(f'typedef struct {{ unsigned char v[{n}]; }} {name};')
        dyn.append(f'struct {name} {{ v:[{n}]u8 }}')
        values = [str(i+11) for i in range(n)]
        cases.append((name,name,name,f'{name}{{v:[{",".join(values)}]}}',
                      [(f'.v[{i}]',v) for i,v in enumerate(values)]))
    for n in (1,2,9):
        name = f'A{n}'
        c.append(f'typedef struct {{ unsigned long long v[{n}]; }} {name};')
        dyn.append(f'struct {name} {{ v:[{n}]u64 }}')
        values = [str(0x1234567800000011+i) for i in range(n)]
        cases.append((name,name,name,f'{name}{{v:[{",".join(values)}]}}',
                      [(f'.v[{i}]',v) for i,v in enumerate(values)]))
    # Keep debug images below the MPS2 code RAM size (4 MiB).
    for name, ct, dt, init, leaves in cases[batch*3:(batch+1)*3]:
        pressures = ([[], ['i32'], ['i32']*3, ['i32']*4, ['i32']*5,
                      ['f64']*9+['i32']] if thumb else
                     [[], ['i32']*6, ['i32']*7, ['i32']*8, ['i32']*9])
        # Returning the aggregate exercises sret consuming the first GP slot.
        for returns_struct in ([False, True] if ct == name else [False]):
            for scenario, prefix in enumerate(pressures):
                key = f'{name}_{int(returns_struct)}_{scenario}'
                cp = [f'{CT[t]} p{i}' for i,t in enumerate(prefix)] + [f'{ct} x','int tail','long long last']
                dp = [f'p{i}:{t}' for i,t in enumerate(prefix)] + [f'x:{dt}','tail:i32','last:i64']
                args = [f'{i+1}.0' if t=='f64' else str(i+1) for i,t in enumerate(prefix)]
                valid = [f'p{i} != {v}' for i,v in enumerate(args)]
                valid += [f'x{path} != {v}' for path,v in leaves] + ['tail != 19','last != 1234605616436508552']
                cond = ' || '.join(valid)
                crt, drt = (ct,dt) if returns_struct else ('int','i32')
                updates = ' '.join(f'x{path} += 1;' for path,_ in leaves)
                creturn = f'{updates} return x;' if returns_struct else 'return 1;'
                c.append(f'{crt} c_{key}({",".join(cp)}) {{ if ({cond}) return ({crt}){{0}}; {creturn} }}')
                cinit = ' '.join(f'x{path} = {v};' for path,v in leaves)
                result = ' && '.join(f'r{path} == {int(v)+1}' for path,v in leaves) if returns_struct else 'r == 1'
                callargs = args+['x','19','1234605616436508552']
                c.append(f'int cb_{key}({crt} (*fn)({",".join(cp)})) {{ {ct} x = {{0}}; {cinit} '
                         f'{crt} r = fn({",".join(callargs)}); return {result}; }}')
                localret = ('y := x '+ ' '.join(f'y{path} += 1' for path,_ in leaves)+' return y') if returns_struct else 'return 1'
                dyn += [f'extern fn c_{key}({",".join(dp)}) {drt}',
                        f'extern fn cb_{key}(f:fn({",".join(prefix+[dt,"i32","i64"])}) {drt}) i32',
                        f'fn local_{key}({",".join(dp)}) {drt} {{ if {cond} {{ #panic("incoming {key}") }} {localret} }}']
                body += [f'x_{key}:{dt} = {init}']
                dargs = ','.join(args+[f'x_{key}','19','1234605616436508552'])
                for indirect in (False,True):
                    callee = f'c_{key}'
                    if indirect:
                        body.append(f'fp_{key} := &c_{key}')
                        callee = f'fp_{key}'
                    r = f'r_{key}_{int(indirect)}'
                    body.append(f'{r} := {callee}({dargs})')
                    failed = [f'{r}{path} != {int(v)+1}' for path,v in leaves] if returns_struct else [f'{r} != 1']
                    failed += [f'x_{key}{path} != {v}' for path,v in leaves]
                    body.append('if '+' || '.join(failed)+f' {{ #panic("outgoing {key}_{int(indirect)}") }}')
                body.append(f'if cb_{key}(&local_{key}) != 1 {{ #panic("callback {key}") }}')
                checks += 3
    # Fixed RV32 pairs split at a7; unnamed pairs instead align to even GP
    # numbers and go wholly to stack. Thumb aligns both kinds to even pairs.
    for named in ((False,True) if batch==0 else ()):
        key = f'variadic_{int(named)}'
        n = 3 if thumb else 7
        cp = [f'int p{i}' for i in range(n)]
        dp = [f'p{i}:i32' for i in range(n)]
        if named:
            cp.append('long long x')
            dp.append('x:i64')
        anchor = 'x' if named else f'p{n-1}'
        getx = '' if named else 'long long x=va_arg(ap,long long);'
        c.append(f'int {key}({",".join(cp)},...) {{ va_list ap; va_start(ap,{anchor}); {getx} '
                 'int tail=va_arg(ap,int); va_end(ap); '
                 f'return x == -81985529216486895LL && tail == 19 && '+
                 ' && '.join(f'p{i} == {i+1}' for i in range(n))+'; }')
        dyn.append(f'extern fn {key}({",".join(dp)},...) i32')
        args = ','.join([str(i+1) for i in range(n)]+['wide','19'])
        body += [f'fp_{key} := &{key}',
                 f'if {key}({args}) != 1 || fp_{key}({args}) != 1 {{ #panic("{key}") }}']
        checks += 2
    (work/'provider.c').write_text(('\n'.join(c)+'\n').replace('18364758544493064720', '18364758544493064720ULL'))
    (source/'main.dyn').write_text('\n'.join(dyn)+'\nfn main() {\nwide:i64 = -81985529216486895\n'+
                                  '\n'.join(body)+'\n_ = io.write_all(io.stdout(), "INTEGER ABI PASS\\n")\n}\n')
    qname = 'qemu-system-arm' if thumb else 'qemu-system-riscv32'
    qemu = shlex.split(os.environ.get('DYN_QEMU_ARM' if thumb else 'DYN_QEMU_RISCV32',''))
    if not qemu:
        if not shutil.which(qname):
            raise SystemExit(f'{qname} required; set DYN_QEMU_ARM / DYN_QEMU_RISCV32')
        qemu = [qname]
    flags = (['--target=arm-none-eabihf','-mcpu=cortex-m7','-mthumb','-mfpu=fpv5-d16','-mfloat-abi=hard'] if thumb else
             ['--target=riscv32-unknown-elf','-march=rv32imafd','-mabi=ilp32d','-mno-relax','-mcmodel=medany'])
    for release in (False,True):
        mode = 'release' if release else 'debug'
        obj, image = work/f'{mode}.o', work/f'{mode}.elf'
        subprocess.run([*shlex.split(os.environ.get('CLANG','clang')), *flags,
                        '-ffreestanding','-fno-stack-protector','-O2' if release else '-O0',
                        '-c',str(work/'provider.c'),'-o',str(obj)], check=True)
        if thumb:
            explicit_arm_addends(obj)
        subprocess.run([DYN,'build',str(source),'--target','thumbv7em-none' if thumb else 'riscv32-none',
                        '--no-cache','--quiet','--link',str(obj),'--output',str(image)]+
                       (['--release'] if release else []), check=True, timeout=120)
        machine = (['-machine','mps2-an500','-semihosting-config','enable=on,target=native'] if thumb else
                   ['-machine','virt','-bios','none'])
        process = subprocess.Popen([*qemu,*machine,'-nographic','-kernel',str(image)],
                                   stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                                   stdin=subprocess.DEVNULL,start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
            raise SystemExit(f'FAIL {target} {mode}: timeout\n{stdout.decode(errors="replace")}\n{stderr.decode(errors="replace")}')
        if process.returncode or b'INTEGER ABI PASS' not in stdout:
            raise SystemExit(f'FAIL {target} {mode}: status {process.returncode}\n{stdout.decode(errors="replace")}\n{stderr.decode(errors="replace")}')
        print(f'PASS {target} integer/aggregate batch {batch} {mode}: {checks} clang/Dyn direction checks', flush=True)


if __name__ == '__main__':
    helper_boundaries()
    compiler_boundaries()
    for target in ('rv32','thumb'):
        for batch in range(5):
            suite(target, batch)
