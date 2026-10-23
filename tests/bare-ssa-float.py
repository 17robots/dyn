#!/usr/bin/env python3
"""Hard-float SSA: 61 named functions x RV32/Thumb x SSA/tree.

ROOT selects the compiler directory; DYN and CLANG override compilers.
DYN_QEMU_RISCV32 / DYN_QEMU_ARM are shell-split QEMU command prefixes.
Container wrappers must mount TMPDIR at the same path and bound the guest
(e.g. timeout 20 qemu-system-arm). Host process groups also have a timeout.
TemporaryDirectory respects TMPDIR and cleans fixtures on success or failure.

The separately compiled Clang oracle supplies expected results, not merely
SSA/tree agreement. Arithmetic NaNs compare by classification; bitcasts and
negation preserve exact payload/sign bits. Float-to-integer inputs stay in
range. Local/global memory is supported; checked arbitrary-pointer memory
remains covered by fallback guards in bare-ssa.py.
"""
import importlib.util
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import tempfile

ROOT = Path(os.environ.get('ROOT', Path(__file__).resolve().parents[1])).resolve()
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))
spec = importlib.util.spec_from_file_location('bare_ssa', ROOT/'tests/bare-ssa.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)

src='use "std/io"\nextern fn oracle() i32\nfn main() { status:=oracle() if status!=0 { _=io.println(io.stdout(),"oracle {}",status) #panic("oracle") } _=io.write_all(io.stdout(),"FLOAT OK\\n") }\n'
c='typedef unsigned long long U; typedef long long I; typedef unsigned W;\n'
checks=[];names=[]
def add(name,args,ret,body,ctargs,ctret):
 global src,c
 names.append(name);src+=f'pub fn {name}({args}) {ret} {{ {body} }}\n';c+=f'extern {ctret} {name}({ctargs});\n'
for width,ct,ut in [(32,'float','W'),(64,'double','U')]:
 t=f'f{width}';it=f'u{width}';s=str(width)
 c+=f'static {ct} f{s}({ut} x) {{ union {{ {ct} f; {ut} u; }} v;v.u=x;return v.f; }}\nstatic {ut} u{s}({ct} x) {{ union {{ {ct} f; {ut} u; }} v;v.f=x;return v.u; }}\n'
 for op,expr in [('add','x+y'),('sub','x-y'),('mul','x*y'),('div','x/y')]:
  add(op+s,f'x:{t},y:{t}',t,'return '+expr,ct+','+ct,ct)
  checks.append(f'if(u{s}({op+s}(a,b))!=u{s}(a{dict(add="+",sub="-",mul="*",div="/")[op]}b)) return CODE;')
 add('neg'+s,f'x:{t}',t,'return -x',ct,ct)
 add('bits'+s,f'x:{t}',it,f'return #bitcast({it},x)',ct,ut)
 add('frombits'+s,f'x:{it}',t,f'return #bitcast({t},x)',ut,ct)
 for op,expr in [('eq','=='),('ne','!='),('lt','<'),('le','<='),('gt','>'),('ge','>=')]:
  add(op+s,f'x:{t},y:{t}','bool',f'return x{expr}y',ct+','+ct,'_Bool')
 add('rem'+s,f'x:{t},y:{t}',t,'return x%y',ct+','+ct,ct)
 src+=f'g{s}:{t}\n'
 add('mem'+s,f'x:{t},y:{t}',t,f'g{s}=x old:=g{s} g{s}=y return old+g{s}',ct+','+ct,ct)
 add('frame'+s,f'x:{t},y:{t}',t,'z:=x p:=&z p.*=p.*+y return z',ct+','+ct,ct)
 add('cycle'+s,f'x:{t},y:{t},z:{t},n:u32',t,'a:=x b:=y d:=z i:u32=0 for i<n { t:=a a=b b=d d=t i=#wrap(i+1) } return a',ct+','+ct+','+ct+',W',ct)
 for sign,ctype in [('i64','I'),('u64','U')]:
  add('to'+sign+s,f'x:{t}',sign,f'return #cast({sign},x)',ct,ctype)
  add('from'+sign+s,f'x:{sign}',t,f'return #cast({t},x)',ctype,ct)
 src+=f'extern fn cf{s}(x:{t}) {t}\n'
 c+=f'{ct} cf{s}({ct} x) {{ return x*2; }}\n'
 add('call'+s,f'x:{t}',t,f'return cf{s}(x)',ct,ct)
 add('callback'+s,f'p:fn({t}) {t},x:{t},wide:u64',t,f'return p(x)+#cast({t},wide)',f'{ct} (*)({ct}),{ct},U',ct)
 add('live'+s,f'x:{t},y:{t},wide:u64',t,f'a:=x+y b:=cf{s}(x) return a+b+y+#cast({t},wide)',ct+','+ct+',U',ct)
 # Exhaust FP, core pairs, and stack, alternating wide and floats.
 args=[];ctargs=[];vals=[]
 for i in range(24):
  ty=t if i%3 else 'u64';args.append(f'a{i}:{ty}');ctargs.append(ct if ty==t else 'U');vals.append(f'{i+1}')
 expr='+'.join(f'#cast({t},a{i})' for i in range(24))
 add('many'+s,','.join(args),t,'return '+expr,','.join(ctargs),ct)
 src+=f'extern fn cmany{s}('+','.join(args)+f') {t}\n'
 c+=f'{ct} cmany{s}('+','.join(f'{ty} a{i}' for i,ty in enumerate(ctargs))+') { return '+'+'.join(f'(W)a{i}' if i%3==0 else f'a{i}' for i in range(24))+'; }\n'
 add('outmany'+s,','.join(args),t,f'return cmany{s}('+','.join(f'a{i}' for i in range(24))+')',','.join(ctargs),ct)
 checks.append(f'if(many{s}('+','.join(vals)+f')!=300 || outmany{s}('+','.join(vals)+')!=300) return CODE;')
for width,ct in [(32,'float'),(64,'double')]:
 t=f'f{width}';params=','.join(f'x{i}:{t}' for i in range(24));ctparams=','.join([ct]*24)
 add(f'fpbank{width}',params,t,'return '+'+'.join(f'x{i}' for i in range(24)),ctparams,ct)
 src+=f'extern fn cfpbank{width}({params}) {t}\n'
 c+=f'{ct} cfpbank{width}('+','.join(f'{ct} x{i}' for i in range(24))+') { return '+'+'.join(f'x{i}' for i in range(24))+'; }\n'
 add(f'fpbankcall{width}',params,t,f'return cfpbank{width}('+','.join(f'x{i}' for i in range(24))+')',ctparams,ct)
add('widen','x:f32','f64','return #cast(f64,x)','float','double')
add('narrowfloat','x:f64','f32','return #cast(f32,x)','double','float')
args=','.join(f'a{i}:'+('f32' if i%3==0 else 'f64' if i%3==1 else 'u64') for i in range(30))
ctargs=','.join('float' if i%3==0 else 'double' if i%3==1 else 'U' for i in range(30))
add('mixed',args,'f64','return '+'+'.join(f'#cast(f64,a{i})' for i in range(30)),ctargs,'double')
src+=f'extern fn cmixed({args}) f64\n'
c+='double cmixed('+','.join(('float' if i%3==0 else 'double' if i%3==1 else 'U')+f' a{i}' for i in range(30))+') { return '+'+'.join(f'(W)a{i}' if i%3==2 else f'a{i}' for i in range(30))+'; }\n'
add('mixedcall',args,'f64','return cmixed('+','.join(f'a{i}' for i in range(30))+')',ctargs,'double')
add('floatwide','x:f64,y:f32','u64','return #bitcast(u64,x)^#cast(u64,#bitcast(u32,y))','double,float','U')
c+='int oracle(void) {\n'
for width in (32,64):
 c+=f'if(fpbank{width}('+','.join(str(i+1) for i in range(24))+f')!=300 || fpbankcall{width}('+','.join(str(i+1) for i in range(24))+')!=300) return 112;\n'
c+='if(mixed('+','.join(str(i+1) for i in range(30))+')!=465 || mixedcall('+','.join(str(i+1) for i in range(30))+')!=465) return 110;\n'
c+='if(floatwide(1.5f,-2.25f)!=(0x3ff8000000000000ULL^0xc0100000U)) return 111;\n'

code=1
for width,ct,ut,patterns in [(32,'float','W',['0','0x80000000','0x7f800000','0xff800000','0x7fc12345','0x3fc00000','0xc0100000','1']),(64,'double','U',['0','0x8000000000000000ULL','0x7ff0000000000000ULL','0xfff0000000000000ULL','0x7ff8123456789abcULL','0x3ff8000000000000ULL','0xc002000000000000ULL','1'])]:
 s=str(width);sign='0x80000000U' if width==32 else '0x8000000000000000ULL'
 c+=f'{{ {ut} patterns[]={{'+','.join(patterns)+f'}}; for(W i=0;i<8;i++) {{ {ct} a=f{s}(patterns[i]);\n'
 for check in [f'u{s}(neg{s}(a))!=(patterns[i]^{sign})',f'bits{s}(a)!=patterns[i]',f'u{s}(frombits{s}(patterns[i]))!=patterns[i]']:
  c+=f'if({check}) return {code};\n';code+=1
 c+=f'for(W j=0;j<8;j++) {{ {ct} b=f{s}(patterns[j]);\n'
 for op,expr in [('eq','=='),('ne','!='),('lt','<'),('le','<='),('gt','>'),('ge','>=')]:
  c+=f'if({op+s}(a,b)!=(a{expr}b)) return {code};\n';code+=1
 for op,expr in [('add','+'),('sub','-'),('mul','*'),('div','/')]:
  c+=f'{{ {ct} got={op+s}(a,b), want=a{expr}b; if(want==want ? u{s}(got)!=u{s}(want) : got==got) return {code}; }}\n';code+=1
 c+='}}}\n'
 c+=f'if(u{s}(rem{s}(f{s}({sign}),2))!={sign} || rem{s}(3,f{s}(patterns_placeholder))!=3) return {code};\n'.replace('patterns_placeholder','0x7f800000' if width==32 else '0x7ff0000000000000ULL');code+=1
 c+=f'{{ {ct} r=rem{s}(1,0); if(r==r) return {code}; }}\n';code+=1

 c+=f'{{ {ct} a=13.5,b=-2.25;\n'
 for check in checks:
  if re.search(r'(?:add|sub|mul|div|many)'+s+r'\(',check):
   c+=check.replace('CODE',str(code))+'\n';code+=1
 for check in [f'rem{s}(a,b)!=0',f'rem{s}(-5.5,2)!=-1.5',f'call{s}(a)!=27',f'callback{s}(cf{s},a,0x100000001ULL)!=({ct})(27+({ct})0x100000001ULL)',f'live{s}(a,b,0x100000001ULL)!=(a+b+2*a+b+({ct})0x100000001ULL)', f'toi64{s}(-123.75)!=-123', f'tou64{s}(0x1p63)!=0x8000000000000000ULL', f'fromi64{s}(-0x123456789abcdefLL)!=({ct})-0x123456789abcdefLL',f'fromu64{s}(0xfedcba9876543210ULL)!=({ct})0xfedcba9876543210ULL']:
  c+=f'if({check}) return {code};\n';code+=1
 c+=f'if(mem{s}(3.25,-7.5)!=-4.25 || frame{s}(3.25,-7.5)!=-4.25) return {code};\n';code+=1
 c+=f'for(W n=0;n<12;n++) {{ {ct} expected=n%3==0?1.25:n%3==1?-2.5:3.75; if(cycle{s}(1.25,-2.5,3.75,n)!=expected) return {code}; }}\n}}\n';code+=1
c+=f'if(widen(1.25f)!=1.25 || narrowfloat(1.234567890123)!=(float)1.234567890123) return {code}; return 0; }}\n'


def check_remarks(log, mode):
    if mode == 'tree':
        assert 'SSA code generation' not in log, log
        return
    for name in names:
        messages = re.findall(r'^remark: ' + re.escape(name) + r': (.*)$', log, re.M)
        assert any(message.startswith('SSA code generation,') for message in messages), (name, log)
        assert not any('tree emitter' in message for message in messages), (name, messages)


def run_guest(command):
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise AssertionError(f'guest exceeded 30 seconds: {command}')
    return process.returncode, stdout.replace(b'\r\n', b'\n'), stderr


def main():
    assert len(names) == len(set(names)) == 61, names
    remarks = ['remark: ' + name + ': SSA code generation, test' for name in names]
    check_remarks('\n'.join(remarks), 'ssa')
    for index, name in enumerate(names):
        try:
            check_remarks('\n'.join(remarks[:index] + remarks[index + 1:]), 'ssa')
        except AssertionError:
            pass
        else:
            raise AssertionError(f'missing named SSA remark accepted: {name}')
    print('PASS hard-float: 61 missing-remark negative controls', flush=True)
    for label, command in [('DYN', [DYN]), ('CLANG', CLANG)]:
        if not command or not shutil.which(command[0]):
            print(f'SKIP hard-float: {label} executable unavailable: {command}', flush=True)
            return
    completed = 0
    for target, variable, program, flags, board in b.TARGETS:
        qemu = shlex.split(os.environ.get(variable, '')) or [program]
        if not shutil.which(qemu[0]):
            print(f'SKIP {target}: {qemu[0]} unavailable; set {variable}', flush=True)
            continue
        with tempfile.TemporaryDirectory(prefix='dyn-ssa-float-') as temporary:
            work = Path(temporary)
            project = work/'source'
            project.mkdir()
            (project/'main.dyn').write_text(src)
            (work/'oracle.c').write_text(c)
            obj = work/'oracle.o'
            # One independent C object is used by both Dyn lowering modes.
            subprocess.run([*CLANG, *flags, '-ffreestanding', '-fno-stack-protector',
                '-ffp-contract=off', '-O2', '-c', str(work/'oracle.c'), '-o', str(obj)],
                check=True, timeout=60)
            if target == 'thumbv7em-none':
                b.arm_addends(obj)
            for mode in ('ssa', 'tree'):
                env = dict(os.environ)
                env.pop('DYN_NO_SSA', None)
                if mode == 'tree':
                    env['DYN_NO_SSA'] = '1'
                image = work/f'{mode}.elf'
                build = subprocess.run([DYN, 'build', str(project), '--release', '--target', target,
                    '--no-cache', '--opt-remarks', '--link', str(obj), '--output', str(image)],
                    env=env, capture_output=True, text=True, timeout=120)
                log = build.stdout + build.stderr
                assert build.returncode == 0, (target, mode, log)
                check_remarks(log, mode)
                actual = run_guest([*qemu, *board, '-nographic', '-kernel', str(image)])
                expected = (0, b'FLOAT OK\n', b'')
                assert actual == expected, (target, mode, expected, actual)
                completed += 1
                print(f'PASS {target} {mode}: 61 named functions; Clang oracle status/output', flush=True)
    if completed:
        print(f'PASS hard-float: {completed}/4 guests; 61 named SSA functions per target; '
              '61 missing-remark negative controls', flush=True)
    else:
        print('SKIP hard-float: no QEMU targets executed', flush=True)


if __name__ == '__main__':
    main()
