#!/usr/bin/env python3
"""Runtime globals, entry points, syscalls and constant-data protection."""
import ctypes
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[2]
DYN=Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve()
CC=shlex.split(os.environ.get('CC','cc'))
SOURCE='''
struct Pair { a:u64,b:u64 }
enum Box { Empty, Value:Pair }
pub counter:u64
fn next() u64 { counter+=1 return counter }
fn plus(value:u64) u64 { return value+10 }
pub first:u64=next()
pub second:u64=next()
pub items:[3]u64=[next(),next(),next()]
pub pair:Pair=Pair{a:next(),b:next()}
pub payload:Box=Box.Value(Pair{a:8,b:9})
pub text:[]const u8="ok"
pub callback:*fn(u64) u64=&plus
extern foreign_value "backend_foreign_value":u64
const frozen:Pair=Pair{a:10,b:20}
const frozen_table:[3]u8=[1,2,3]
const frozen_text:[]const u8="ice"
const frozen_callback:*fn(u64) u64=&plus
const computed:u64=15
pub fn constants() u64 {
  total:=frozen.a+frozen.b+#cast(u64, frozen_table[2])+#cast(u64, #len(frozen_text))+frozen_callback(1)+computed
  return total
}
pub fn frozen_pointer() rawptr { return #cast(rawptr, &frozen) }
pub fn state() u64 {
  total:=counter+first+second+items[0]+items[1]+items[2]+pair.a+pair.b+#cast(u64, #len(text))+callback(1)+foreign_value
  case payload { Box.Value p=>{return total+p.a+p.b}, _=>{return 0} }
}
pub fn mutate(value:u64) u64 { pair.a=value items[1]=value foreign_value=value return pair.a+items[1]+foreign_value }
pub fn pid() isize { return #syscall(39) }
pub fn unknown_syscall() isize { return #syscall(999999) }
pub fn write_text() isize { return #syscall(1,1,&text[0],#len(text)) }
pub fn reflect() u64 {
  info:=#typeof(Pair)
  if info.kind!=TypeKind.Struct { #panic("reflection kind") }
  if info.fields[0].name[0]!='a' || info.fields[1].name[0]!='b' { #panic("reflection fields") }
  return #cast(u64, (info.size+info.member_count+#len(info.fields)+#len(info.name)))
}
'''
PROVIDER='unsigned long backend_foreign_value=11;\n'
COLLISIONS='unsigned long next(void){return 999;} unsigned long plus(unsigned long x){return x+999;} unsigned long frozen=999;\n'
def run(args):
    result=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=120)
    assert result.returncode==0,(args,result.returncode,result.stdout,result.stderr)
    return result

def main():
    checks=0
    with tempfile.TemporaryDirectory(prefix='dyn-backend-globals-') as directory:
        root=Path(directory); source=root/'main.dyn';source.write_text(SOURCE)
        provider=root/'provider.c';provider.write_text(PROVIDER);provider_obj=root/'provider.o'
        run([*CC,'-fPIC','-c',provider,'-o',provider_obj])
        # C definitions with the names of private Dyn symbols must not replace them.
        collisions=root/'collisions.c';collisions.write_text(COLLISIONS);collisions_obj=root/'collisions.o'
        run([*CC,'-fPIC','-c',collisions,'-o',collisions_obj])
        for mode in ('debug','release'):
            oracle=root/(mode+'-compiler.so');run([DYN,'build',root,'--shared','--'+mode,'--no-cache','--jobs','1','--link',provider_obj,'--link',collisions_obj,'--output',oracle])
            for path in (oracle,):
                lib=ctypes.CDLL(str(path))
                for name,expected in (('state',76),('pid',os.getpid()),('unknown_syscall',-38),('reflect',24),('constants',62)):
                    f=getattr(lib,name);f.argtypes=[];f.restype=ctypes.c_int64
                    actual=f();assert actual==expected,(mode,path,name,actual,expected);checks+=1
                f=lib.mutate;f.argtypes=[ctypes.c_uint64];f.restype=ctypes.c_uint64
                assert f(19)==57;checks+=1
                code='import ctypes,sys; lib=ctypes.CDLL(sys.argv[1]); lib.write_text.restype=ctypes.c_longlong; assert lib.write_text()==2'
                result=run([sys.executable,'-c',code,path]);assert result.stdout=='ok',result.stdout;checks+=1
                code='import ctypes,sys;lib=ctypes.CDLL(sys.argv[1]);lib.frozen_pointer.restype=ctypes.c_void_p;ctypes.c_uint64.from_address(lib.frozen_pointer()).value=0'
                result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True,timeout=10)
                assert result.returncode==-11,(mode,path,result.returncode,result.stderr);checks+=1
            # Freestanding runtime calls main directly; no CRT constructor walker.
            source.write_text(SOURCE+'\nfn main() { if state()!=76 { #panic("global startup") } _=write_text() return }\n')
            executable=root/(mode+'-compiler');run([DYN,'build',root,'--'+mode,'--no-cache','--jobs','1','--link',provider_obj,'--link',collisions_obj,'--output',executable])
            assert run([executable]).stdout=='ok';checks+=1
            for failure in (
                'fn seed() u64 { #panic("initializer failure") } pub value:u64=seed()\nfn main() {}\n',
                'zero:u64 pub value:u64=1/zero\nfn main() {}\n',
            ):
                source.write_text(failure)
                for shared in (True,False):
                    oracle=root/(mode+'-failure'+('.so' if shared else ''))
                    run([DYN,'build',root,*(['--shared'] if shared else []),'--'+mode,'--no-cache','--jobs','1','--output',oracle])
                    command=[sys.executable,'-c','import ctypes,sys;ctypes.CDLL(sys.argv[1])',str(oracle)] if shared else [str(oracle)]
                    result=subprocess.run(command,capture_output=True,text=True,timeout=10)
                    assert result.returncode==101,(mode,oracle,result.returncode,result.stderr);checks+=1
            source.write_text(SOURCE)
    print(f'PASS {checks} runtime-global/startup/syscall checks')
if __name__=='__main__':main()
