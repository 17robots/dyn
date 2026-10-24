#!/usr/bin/env python3
"""Versioned structural IR is deterministic, relocatable, and emits no machine code."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
MAIN=r'''use "dep" d
struct Pair { left:i64, right:f64 }
enum(u8) Tag { A=0,B=1 }
const maximum:u64=18446744073709551615
const message:[]const u8="a\x00\xffz"
global:i32=3
extern fn absent "unlinked_symbol"(x:i32) i32
fn identity(x:$T) T { return x }
fn callback(x:i32) i32 { return x+1 }
fn work(values:[]i32,which:Tag) i64 {
  p:=Pair{left:7,right:1.5}
  for i in 0..#len(values) { values[i]+=global }
  for value in values { if value>10 { continue }
  p.left+=#cast(i64,value) }
  case which { Tag.A=>{ p.left+=1 }Tag.B=>{ p.left+=2 } }
  defer { global=4 }
  return identity(p.left)+d.read(d.Item{value:2})
}
fn main() {
  minimum:i64=-9223372036854775808
  _=minimum
  values:[3]i32=[1,2,3]
  pointer:*i32=&values[0]
  _=pointer[..3]
  _=work(values[..],Tag.A)
  _=d.generic(d.Item{value:7})
  target:fn(i32) i32=callback
  _=target(1)
  _=#bitcast(u64,#cast(f64,1.5))
  _=message
  _=maximum
}
'''
DEP='pub struct Item { value:i64 }\npub fn read(x:Item) i64 { return x.value }\npub fn generic(x:$T) T { return x }\n'

def execute(project,*args,env=None):
    return subprocess.run([DYN,'build',str(project),'--emit-ir',*args],env=env,capture_output=True,timeout=90)

def sections(data):
    lines=data.decode('ascii').splitlines()
    assert lines[0]=='dyn-ir1' and lines[-1]=='end'
    assert data.endswith(b'\n') and b'\r' not in data
    i=2
    names=[]
    while i<len(lines)-1:
        tag,name,count=lines[i].split()
        assert tag=='section' and name not in names
        names.append(name)
        i+=1+int(count)
    assert i==len(lines)-1
    return names

with tempfile.TemporaryDirectory(prefix='dyn-ir-dump-') as temporary:
    work=Path(temporary)
    project=work/'first'/'app';project.mkdir(parents=True)
    (project/'main.dyn').write_text(MAIN)
    (project/'dep').mkdir();(project/'dep'/'dep.dyn').write_text(DEP)
    env=dict(os.environ,DYN_SDK=str(ROOT),DYN_CACHE_DIR=str(work/'cache'))
    first=execute(project,'--target','x86_64-linux',env=env)
    assert first.returncode==0,first.stderr
    names=sections(first.stdout)
    assert len(names)==21,names
    assert b'bytes=4:6100ff7a' in first.stdout
    assert b'signed_literal=true' in first.stdout
    assert b'bits=ffffffffffffffff' in first.stdout
    assert b'bits=3ff8000000000000' in first.stdout
    assert b'unlinked_symbol'.hex().encode() in first.stdout
    assert str(project).encode() not in first.stdout
    for jobs in ('1','4'):
        repeat=execute(project,'--jobs',jobs,'--target','x86_64-linux',env=env)
        assert repeat.returncode==0 and repeat.stdout==first.stdout,repeat.stderr
    relocated=work/'elsewhere'/'app';shutil.copytree(project,relocated)
    other=execute(relocated,'--target','x86_64-linux',env=env)
    assert other.returncode==0 and other.stdout==first.stdout,other.stderr
    relocated_sdk=work/'sdk';relocated_sdk.mkdir()
    shutil.copytree(ROOT/'std',relocated_sdk/'std')
    stdproject=work/'stdapp';stdproject.mkdir()
    (stdproject/'main.dyn').write_text('use "std/math" m\nfn main(){ _=m.max(#cast(i32,1),#cast(i32,2)) }')
    sdkone=execute(stdproject,env=env)
    sdktwo=execute(stdproject,env=dict(env,DYN_SDK=str(relocated_sdk)))
    assert sdkone.returncode==sdktwo.returncode==0,(sdkone.stderr,sdktwo.stderr)
    assert sdkone.stdout==sdktwo.stdout,'SDK relocation changed semantic dump'
    output=work/'snapshot.ir'
    for _ in range(2):
        written=execute(project,'--target','x86_64-linux','--output',str(output),env=env)
        assert written.returncode==0 and written.stdout==b'' and output.read_bytes()==first.stdout,written.stderr
    assert not list(work.glob('snapshot.ir.tmp.*'))
    for target in ('riscv32-none-soft','thumbv7em-none-soft','wasm32-browser','wasm32-wasi'):
        dumped=execute(project,'--target',target,env=env)
        assert dumped.returncode==0,dumped.stderr
        sections(dumped.stdout)
        assert target.encode().hex().encode() in dumped.stdout
    for command,args in [('run',[]),('check',[]),('query',[]),('build',['--release']),('build',['--emit-object']),('build',['--emit-asm']),('build',['--link','missing.o']),('build',['--cpu','native'])]:
        bad=subprocess.run([DYN,command,str(project),'--emit-ir',*args],env=env,capture_output=True,timeout=20)
        assert bad.returncode==2 and not bad.stdout,(command,args,bad)
    for flags in (['--bogus','--emit-ir'], ['--emit-ir','--bogus']):
        bad=subprocess.run([DYN,'build',str(project),*flags],env=env,capture_output=True,timeout=20)
        assert bad.returncode==2 and not bad.stdout,(flags,bad)
    (project/'main.dyn').write_text('fn main(){ missing() }')
    failed=execute(project,'--output',str(output),env=env)
    assert failed.returncode==1 and not failed.stdout and output.read_bytes()==first.stdout,failed
    assert not list(project.rglob('*.o')) and not list(project.rglob('*.wasm'))
    if (work/'cache').exists():
        assert not list((work/'cache').rglob('native-*.o'))
print('PASS structural IR: byte encoding, references, deterministic jobs/relocation, target selection, atomic files, conflicts, no codegen')
