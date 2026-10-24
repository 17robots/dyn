#!/usr/bin/env python3
"""Known-zero aggregate copies retain exact byte extents and use target zero fills."""
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
SIZES = (1, 3, 7, 8, 9, 15, 16, 17, 31, 32, 33, 63, 64, 65, 72, 127, 128)


def source(guard):
    declarations = ['use "std/io" io', 'fn expect(ok:bool) { if !ok { #panic("zero copy") } }']
    checks = []
    for size in SIZES:
        declarations += [f'struct Z{size} {{ a:[{size}]u8 }}',
                         f'pub fn zero{size}(p:*Z{size}) {{ r:Z{size} p.*=r }}']
        checks += [f'''for offset in 0..16 {{
  for i in 0..320 {{ backing[i]=171 }}
  zero{size}(#cast(*Z{size},&backing[offset]))
  for i in 0..320 {{ expected:u8=171 if i>=offset && i-offset<{size} {{ expected=0 }} expect(backing[i]==expected) }}
}}''']
        if guard:
            checks += [f'''zero{size}(#cast(*Z{size},&page[0]))
zero{size}(#cast(*Z{size},#cast(usize,&page[0])+4096-{size}))''']
    declarations += ['''struct Padded { a:u8,b:u64,c:u8 }
pub fn padded(p:*Padded) { r:Padded p.*=r }
pub fn partial(p:*Z64) { r:Z64 r.a[31]=91 p.*=r }
pub fn unknown(p:*Z64,x:u8) { r:Z64 r.a[31]=x p.*=r }
pub fn overlap() {
  r:[67]u8
  for i in 0..67 { r[i]=#cast(u8,i) }
  (#cast(*Z64,&r[1])).*=(#cast(*Z64,&r[0])).*
  expect(r[0]==0 && r[65]==65 && r[66]==66)
  for i in 1..65 { expect(r[i]==#cast(u8,i-1)) }
}''']
    # Padded destinations respect their real alignment; byte-array structs above
    # deliberately permit every address residue.
    checks += ['''for i in 0..320 { backing[i]=171 }
  padded(#cast(*Padded,&backing[0]))
  for i in 0..#sizeof(Padded) { expect(backing[i]==0) }
  for i in #sizeof(Padded)..320 { expect(backing[i]==171) }
  partial(#cast(*Z64,&backing[1]))
  for i in 0..64 { expected:u8=0 if i==31 { expected=91 } expect(backing[i+1]==expected) }
  unknown(#cast(*Z64,&backing[3]),255)
  for i in 0..64 { expected:u8=0 if i==31 { expected=255 } expect(backing[i+3]==expected) }
  overlap()''']
    pre = 'backing:[320]u8\n'
    if guard:
        pre += '''mapped:=#syscall(9,0,12288,0,34,-1,0)
expect(mapped>0) expect(#syscall(10,mapped+4096,4096,3)==0)
page:=(#cast(*u8,mapped+4096))[..4096]
'''
        checks += ['expect(#syscall(11,mapped,12288)==0)']
    return '\n'.join(declarations)+ '\nfn main() {\n'+pre+'\n'.join(checks)+'\n_=io.write_all(io.stdout(),"ZERO COPY PASS\\n")\n}\n'


def shape(binary, expected=True):
    assembly = subprocess.check_output(['objdump','-d','-Mintel',str(binary)],text=True)
    for size in (32, 64):
        body = re.search(r'<zero'+str(size)+r'>:\n(.*?)(?=\n\n|\Z)',assembly,re.S).group(1)
        stores = re.findall(r'\tmov\w*\s+[^,\n]*\[[^\n]*,',body)
        # Baseline manufactures one byte store per byte for an unknown pointer.
        # Zero-fill lowering uses at most size/8 stores on x86, even when odd.
        if expected:
            assert len(stores)<=size//8 and 'rep movs' not in body, body
        else:
            assert len(stores)>=size, body
    # 72-byte sources remain outside the existing SSA_TRACKED=64 limit.
    fallback = re.search(r'<zero72>:\n(.*?)(?=\n\n|\Z)',assembly,re.S).group(1)
    assert 'movs' in fallback or re.search(r'\bmov\w*\s+\w+,.*\[',fallback),fallback
    return assembly


UNIT = '#define DYN_BACKEND_EMBEDDED\n#include "backend/driver.c"\n#include <assert.h>\nint main(void) {\n  SsaValue values[1]={{.op=SO_COPYMEM,.a=17,.b=23,.c=-1,.aux=32,.aux2=1}};\n  uint32_t ids[1]={0}; SsaBlock blocks[1]={0};\n  blocks[0].values.items=ids; blocks[0].values.count=1;\n  Ssa s={.values=values,.value_count=1,.blocks=blocks,.block_count=1};\n  int32_t owner[64]; for(unsigned i=0;i<64;i++)owner[i]=SSA_ZERO;\n  assert(ssa_copy_known(&s,0,0,owner,NULL));\n  assert(values[0].op==SO_ZEROMEM && values[0].a==17 && values[0].aux==32);\n  assert(values[0].b==-1 && values[0].c==-1 && values[0].aux2==0 && s.value_count==1);\n  values[0]=(SsaValue){.op=SO_COPYMEM,.a=17,.b=23,.c=-1,.aux=0,.aux2=1};\n  assert(!ssa_copy_known(&s,0,0,NULL,NULL));\n  assert(values[0].op==SO_COPYMEM && values[0].aux2==1 && s.value_count==1);\n  return 0;\n}\n'

def run(work):
    # Constructed zero-size and pre-marked nonoverlap copies exercise guards
    # that source-level zero-sized aggregates cannot reach on this backend.
    (work/'unit.c').write_text(UNIT)
    subprocess.run([os.environ.get('CC','cc'),'-std=c11','-D_POSIX_C_SOURCE=200809L','-O2','-ffunction-sections','-fdata-sections','-I'+str(ROOT/'src'),str(work/'unit.c'),'-Wl,--gc-sections','-o',str(work/'unit')],check=True,timeout=120)
    subprocess.run([str(work/'unit')],check=True,timeout=10)
    print('PASS zero copy constructed zero-size/nonoverlap controls',flush=True)
    project=work/'source';project.mkdir(exist_ok=True)
    targets=[('host',[])]
    for target,program,board in [
        ('riscv32-none','qemu-system-riscv32',['-machine','virt','-bios','none']),
        ('riscv32-none-soft','qemu-system-riscv32',['-machine','virt','-cpu','sifive-e31','-bios','none']),
        ('thumbv7em-none','qemu-system-arm',['-machine','mps2-an500','-semihosting-config','enable=on,target=native']),
        ('thumbv7em-none-soft','qemu-system-arm',['-machine','mps2-an500','-semihosting-config','enable=on,target=native'])]:
        qemu=shutil.which(program)
        if not qemu and Path('/tmp/dyn-qemu',program).exists():qemu=str(Path('/tmp/dyn-qemu',program))
        if qemu:targets.append((target,[qemu,*board,'-nographic','-kernel']))
        else:print('SKIP',target,'missing',program,flush=True)
    for target,runner in targets:
        guard=target=='host' and platform.system()=='Linux' and platform.machine()=='x86_64'
        (project/'main.dyn').write_text(source(guard))
        modes=['ssa','tree']
        for mode in modes:
            output=work/(target+'-'+mode)
            env=dict(os.environ,DYN_NO_SSA='1' if mode=='tree' else '0')
            command=[DYN,'build',str(project),'--release','--opt-level','2','--no-cache','--quiet','--opt-remarks','--output',str(output)]
            if target!='host':command += ['--target',target]
            result=subprocess.run(command,cwd=ROOT,env=env,capture_output=True,timeout=120)
            assert result.returncode==0,result.stderr
            (work/(output.name+'.build.log')).write_bytes(result.stderr)
            if mode=='ssa':
                assert b'remark: zero64: SSA code generation,' in result.stderr,result.stderr
            result=subprocess.run([*runner,str(output)],capture_output=True,timeout=15)
            assert result.returncode==0 and result.stdout.replace(b'\r\n',b'\n')==b'ZERO COPY PASS\n',(target,mode,result.returncode,result.stdout,result.stderr)
            if target=='host' and mode=='ssa' and guard:
                (work/'fixed.asm').write_text(shape(output))
            print('PASS zero copy',target,mode,flush=True)
    baseline=os.environ.get('DYN_ZERO_BASELINE')
    if baseline and platform.system()=='Linux' and platform.machine()=='x86_64':
        (project/'main.dyn').write_text(source(True));output=work/'baseline'
        subprocess.run([baseline,'build',str(project),'--release','--opt-level','2','--no-cache','--quiet','--output',str(output)],cwd=ROOT,check=True,timeout=120)
        subprocess.run([str(output)],check=True,capture_output=True,timeout=15)
        (work/'baseline.asm').write_text(shape(output,False))
        print('PASS baseline negative shape control',flush=True)

if __name__=='__main__':
    retained=os.environ.get('DYN_ZERO_COPY_ARTIFACTS')
    if retained:
        work=Path(retained).resolve();work.mkdir(parents=True,exist_ok=True);run(work)
    else:
        with tempfile.TemporaryDirectory(prefix='dyn-zero-copy-') as directory:run(Path(directory))
