#!/usr/bin/env python3
"""Uniform private scalar parameters specialize without cloning or lost effects."""
import ctypes
import os
import platform
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
DYN=Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve()
ENV={**os.environ,'DYN_SDK':str(ROOT)}
SOURCE=r'''
use "std/io" io
input: u64 = 1234567890123456789
state: u64 = 0
fn next() u64 { state += 1
return state }
fn digit_sum(value, radix: u64) u64 {
  remaining := value
  total: u64 = 0
  for remaining > 0 {
    total += remaining % radix
    remaining /= radix
  }
  return total
}
fn conflicting(value, radix: u64) u64 {
  remaining := value
  total: u64 = 0
  for remaining > 0 { total += remaining % radix
remaining /= radix }
  return total
}
fn dynamic(value, radix: u64) u64 {
  remaining := value
  total: u64 = 0
  for remaining > 0 { total += remaining % radix
remaining /= radix }
  return total
}
fn mutable(value, radix: u64) u64 {
  radix += 1
  remaining := value
  total: u64 = 0
  for remaining > 0 { total += remaining % radix
remaining /= radix }
  return total
}
fn addressed(value, radix: u64) u64 {
  pointer := &radix
  pointer.* += 1
  remaining := value
  total: u64 = 0
  for remaining > 0 { total += remaining % radix
remaining /= radix }
  return total
}
fn escaped(value, radix: u64) u64 {
  remaining := value
  total: u64 = 0
  for remaining > 0 { total += remaining % radix
remaining /= radix }
  return total
}
global_callback: fn(u64,u64)u64 = global_escaped
fn global_escaped(value, radix: u64) u64 {
  remaining := value
  total: u64 = 0
  for remaining > 0 { total += remaining % radix
remaining /= radix }
  return total
}
fn dead_take() { _ = dead_escaped }
fn dead_escaped(value, radix: u64) u64 {
  remaining := value
  total: u64 = 0
  for remaining > 0 { total += remaining % radix
remaining /= radix }
  return total
}
pub fn public_sum(value, radix: u64) u64 {
  remaining := value
  total: u64 = 0
  for remaining > 0 { total += remaining % radix
remaining /= radix }
  return total
}
fn recurse(value, radix: u64) u64 {
  if value == 0 { return 0 }
  return value % radix + recurse(value / radix, radix)
}
fn recursive_constant(value, radix: u64) u64 {
  if value == 0 { return 0 }
  return value % radix + recursive_constant(value / radix, 10)
}
fn flags(value:u64, flag:bool, tag:u8) u64 {
  total := value
  for i in 0..3 {
    if flag { total += #cast(u64, tag) }
  }
  return total
}
fn mask64(value, mask:u64) u64 {
  total := value
  for i in 0..4 { total ^= (value + #cast(u64,i)) & mask }
  return total
}
fn narrow(value:i64, amount:i8) i64 {
  total := value
  for i in 0..3 { total += #cast(i64, amount) }
  return total
}
fn main() {
  if digit_sum(input,10) != 90 || digit_sum(input+1,10) != 82 { #panic("uniform") }
  if conflicting(input,10) != 90 || conflicting(input,16) != 84 { #panic("conflict") }
  radix := next() + 9
  if dynamic(input,radix) != 90 { #panic("dynamic") }
  if mutable(input,10) != 79 || addressed(input,10) != 79 { #panic("mutable") }
  callback := escaped
  if escaped(input,10) != 90 || callback(input,16) != 84 { #panic("escaped") }
  if global_escaped(input,10) != 90 || global_callback(input,16) != 84 { #panic("global escape") }
  if dead_escaped(input,10) != 90 { #panic("dead escape") }
  if public_sum(input,10) != 90 { #panic("public") }
  if recurse(input,10) != 90 || recursive_constant(input,10) != 90 { #panic("recursive") }
  if flags(next(),true,'A') != 197 { #panic("flags/order") }
  if narrow(-20,-3) != -29 { #panic("negative narrow") }
  if mask64(input,1311768467463790320) != 1234567890123456789 { #panic("large mask") }
  if state != 2 { #panic("argument effects") }
}
'''

def run(*args,success=True,env=None):
    result=subprocess.run(list(map(str,args)),cwd=ROOT,env=env or ENV,text=True,capture_output=True,timeout=120)
    assert (result.returncode==0)==success,(args,result.stdout,result.stderr)
    return result


def build(project,output,*flags,cache=False,env=None):
    return run(DYN,'build',project,'--quiet','--output',output,*flags,*([] if cache else ['--no-cache']),env=env)


def body(output,name):
    text=run('objdump','-d','--disassemble='+name,output).stdout
    assert '<'+name+'>:' in text,(name,text)
    return text


with tempfile.TemporaryDirectory(prefix='dyn-uniform-params-') as temporary:
    root=Path(temporary);project=root/'module';project.mkdir();source=project/'main.dyn';source.write_text(SOURCE)
    for mode,flags,environment in [('debug',['--debug'],ENV),('o1',['--release','--opt-level','1'],ENV),('o2',['--release'],ENV),('o3',['--release','--opt-level','3'],ENV),('debug-info',['--release','--debug-info'],ENV),('tree',['--release'],{**ENV,'DYN_NO_SSA':'1'})]:
        output=root/mode;build(project,output,*flags,env=environment);run(output,env=environment)
        if mode=='o2' and platform.machine().lower() in ['x86_64','amd64'] and shutil.which('objdump'):
            assert not re.search(r'\b(?:i?div)\s',body(output,'digit_sum'))
            # The O2 ranked inliner may fold these into main; any that stay
            # out of line must keep their runtime division.
            symbols=run('nm',output).stdout
            for name in ['conflicting','dynamic','mutable','addressed','escaped','global_escaped','public_sum','recurse']:
                if re.search(r' [tT] '+name+r'$',symbols,re.M):
                    assert re.search(r'\b(?:i?div)\s',body(output,name)),name
            # Only unreachable code takes dead_escaped, so its reference is not
            # an escape and the uniform radix may still specialize it.
            if re.search(r' [tT] dead_escaped$',symbols,re.M):
                assert not re.search(r'\b(?:i?div)\s',body(output,'dead_escaped'))
            assert not re.search(r'\bcall\b',body(output,'digit_sum'))
            # Wide mask stays in its parameter register instead of becoming
            # a repeatedly materialized movabs constant in the loop.
            if re.search(r' [tT] mask64$',symbols,re.M):
                mask=body(output,'mask64')
                assert not re.search(r'\bmovabs\b',mask),mask
                assert re.search(r'\band\s+%[a-z0-9]+,%[a-z0-9]+',mask),mask
        if mode in ['tree','debug-info'] and platform.machine().lower() in ['x86_64','amd64'] and shutil.which('objdump'):
            assert re.search(r'\b(?:i?div)\s',body(output,'digit_sum'))
    for target,runner in [('aarch64-linux','qemu-aarch64'),('riscv64-linux','qemu-riscv64')]:
        if shutil.which(runner):
            output=root/target;build(project,output,'--release','--target',target);run(runner,output)
    # Public ABI stays general even when internal calls all use ten.
    shared=root/'uniform.so';build(project,shared,'--release','--shared')
    library=ctypes.CDLL(str(shared));function=library.public_sum
    function.argtypes=[ctypes.c_uint64,ctypes.c_uint64];function.restype=ctypes.c_uint64
    assert function(1234567890123456789,16)==84
    # Callee is another file in the same module. Warm-cache caller edits must
    # invalidate inferred facts without a signature/body change to the callee.
    helper=project/'helper.dyn';helper.write_text(SOURCE[SOURCE.index('fn digit_sum('):SOURCE.index('fn conflicting(')])
    for radix,expected in [(10,90),(16,84),(10,90)]:
        source.write_text('use "std/io" io\ninput:u64=1234567890123456789\nfn main(){io.println("{}",digit_sum(input,'+str(radix)+'))}\n')
        executable=root/'cached';build(project,executable,'--release',cache=True,env={**ENV,'DYN_CACHE_DIR':str(root/'cache')})
        assert run(executable).stdout==str(expected)+'\n'
        # A second unchanged build exercises native/executable cache hits too.
        build(project,executable,'--release',cache=True,env={**ENV,'DYN_CACHE_DIR':str(root/'cache')})
        assert run(executable).stdout==str(expected)+'\n'
    helper.unlink()
    # Exact typed literals retain high bits, signs and target-width semantics.
    types=[('u8','255'),('u16','65535'),('u32','4294967295'),('u64','18446744073709551615'),('i8','-128'),('i16','-32768'),('i32','-2147483648'),('i64','-9223372036854775807 - 1'),('usize','255'),('isize','-128')]
    declarations=[];checks=[]
    for kind,constant in types:
        declarations.append('global_'+kind+':'+kind+'=0\nfn typed_'+kind+'(value,marker:'+kind+')'+kind+' { total:=value\nfor i in 0..3 { total ^= marker }\nreturn total }\n')
        checks.append('if typed_'+kind+'(global_'+kind+','+constant+') != '+constant+' { #panic("typed '+kind+'") }\n')
    source.write_text(''.join(declarations)+'fn main(){\n'+''.join(checks)+'}\n')
    for flags in [['--debug'],['--release'],['--release','--opt-level','3']]:
        executable=root/'typed';build(project,executable,*flags);run(executable)
    # A uniform zero must still fail in the callee, after argument effects,
    # without moving observations or deferred cleanup.
    source.write_text('''use "std/io" io
state:u64=0
fn next()u64{state+=1
return state}
fn divide_loop(value,radix:u64)u64{ remaining:=value
for remaining>0{ remaining/=radix }
return remaining }
fn main(){ defer{io.println("cleanup {}",state)}
_ = divide_loop(next(),0) }
''')
    for flags in [['--debug'],['--release'],['--release','--opt-level','3']]:
        executable=root/'panic';build(project,executable,*flags);result=run(executable,success=False)
        assert result.stdout=='cleanup 1\n',result
        assert re.match(r'^runtime check failed \(divide.ok\) in divide_loop(?:\n| at )',result.stderr),result
    source.write_text('''use "std/io" io
state:u64=0
fn next_min()i64{state+=1
return -9223372036854775807 - 1}
fn signed_loop(value,divisor:i64)i64{ result:i64=0
for i in 0..1 { result=value/divisor }
return result }
fn main(){defer{io.println("cleanup {}",state)}
_ = signed_loop(next_min(),-1) }
''')
    for flags in [['--debug'],['--release'],['--release','--opt-level','3']]:
        executable=root/'signed-panic';build(project,executable,*flags);result=run(executable,success=False)
        assert result.stdout=='cleanup 1\n',result
        assert re.match(r'^runtime check failed \(division\.overflow\.ok\) in signed_loop(?:\n| at )',result.stderr),result
    # No cloning: one function symbol remains despite several identical sites.
    if shutil.which('nm'):
        assert len(re.findall(r'\bdigit_sum\S*$',run('nm',root/'o2').stdout,re.M))==1
print('PASS uniform private parameters: loops, mixed/runtime values, mutation/addresses, callbacks, public ABI, recursive/narrow/bool/char values, effects/panics, cross-file warm-cache invalidation and no cloning (debug/O1/O2/O3/tree/debug-info and available cross targets)')
