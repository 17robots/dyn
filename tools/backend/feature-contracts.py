#!/usr/bin/env python3
"""Enum/any/variadic qualification; --oracle-only validates the reference first."""
import argparse
import ctypes
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
BUILD = Path(os.environ.get('BUILD', ROOT / 'build')).resolve()
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve()
CC = shlex.split(os.environ.get('CC', 'cc'))
SOURCE = '''
enum(u8) Small { Zero, One }
enum(i8) Signed { Low=-128, Zero=0, High=127 }
enum(u64) Wide { Zero=0, High=18446744073709551615 }
pub small_global:Small=Small.One
pub signed_global:Signed=Signed.Low
pub fn small_global_set(value:u8) i64 { small_global=#cast(Small, value)
return #cast(i64, small_global) }
pub fn signed_global_set(value:i64) i64 { signed_global=#cast(Signed, value)
return #cast(i64, signed_global) }
enum(u8) Message { Empty, Number: i64, Byte: u8 }
struct Pair { a: i64, b: i64 }
enum Box { Empty, Value: Pair }
pub fn enum_identity(value: Message) Message { return value }
pub fn box_identity(value: Box) Box { return value }
pub fn enum_cross(f:fn(Message) Message,value:i64) i64 {
  result := f(Message.Number(value))
  case result { Message.Number number => { return number } _ => { return -1 } }
}
pub fn box_cross(f:fn(Box) Box,value:i64) i64 {
  result := f(Box.Value(Pair{a:value,b:7}))
  case result { Box.Value pair => { return pair.a+pair.b } _ => { return -1 } }
}
fn inspect(value: any) i64 {
  copy := value
  case copy {
    is i64 number => { return number }
    is bool yes => { if yes { return 1 } else { return 0 } }
    is Pair pair => { return pair.a + pair.b }
    is [2]i64 values => { return values[0]+values[1] }
    is f64 number => { return #cast(i64, number) }
    is Message message => {
      case message { Message.Number number=>{return number} _=>{return -2} }
    }
    is []const u8 text => { return #cast(i64, #len(text)) }
    _ => { return -1 }
  }
}
fn sum(values: ...i64) i64 {
  total: i64 = 0
  for value in values { total += value }
  return total
}
fn mixed(values: ...any) i64 {
  total: i64 = 0
  for value in values { total += inspect(value) }
  return total
}
pub fn plain(value: u8) u64 {
  small := #cast(Small, value)
  case small { Small.Zero => { return 11 } Small.One => { return 22 } }
}
pub fn signed_tag(value:i64) i64 { return #cast(i64, #cast(Signed, value)) }
pub fn wide_tag(value:u64) u64 { return #cast(u64, #cast(Wide, value)) }
pub fn wrong_signed_tag(value:i64) u64 { return #cast(u64, #cast(Wide, value)) }
pub fn payload(value: i64) i64 {
  message := Message.Number(value)
  case message { Message.Number *number => { number += 3 } _ => {} }
  copy := enum_identity(message)
  case copy { Message.Number number => { return number } _ => { return -1 } }
}
pub fn aggregate_payload(value: i64) i64 {
  box := box_identity(Box.Value(Pair{a:value, b:7}))
  case box { Box.Value pair => { return pair.a + pair.b } _ => { return -1 } }
}
pub fn boxed(value: i64) i64 { return inspect(value) }
pub fn boxed_pair(value: i64) i64 { return inspect(Pair{a:value,b:7}) }
pub fn boxed_array(value:i64) i64 { return inspect([value,#cast(i64, 7)]) }
pub fn boxed_enum(value:i64) i64 { return inspect(Message.Number(value)) }
pub fn boxed_float(value:f64) i64 { return inspect(value) }
pub fn boxed_identity(value: u8) i64 { return inspect(value) }
pub fn boxed_bool(value: bool) i64 { return inspect(value) }
pub fn typed_pack(value: i64) i64 { return sum(value,2,3) + sum() }
pub fn any_pack(value: i64) i64 { return mixed(value,true,"dyn",Pair{a:2,b:3}) + mixed() }
fn exhausted(a:i64,b:i64,c:i64,d:i64,e:i64,f:i64,values:...i64) i64 {
  total := a+b+c+d+e+f
  for value in values { total += value }
  return total
}
fn pair_pack(values:...Pair) i64 {
  total:i64=0
  for pair in values { total += pair.a+pair.b }
  return total
}
pub fn native_spills(value:i64) i64 { return exhausted(1,2,3,4,5,6,value,8,9) }
pub fn native_aggregate(value:i64) i64 { return pair_pack(Pair{a:value,b:2},Pair{a:3,b:4}) }
pub fn payload_copy(value:i64) i64 {
  original := Message.Number(value)
  copy := original
  case original { Message.Number *number => { number=9 } _=>{} }
  case copy { Message.Number number => { return number } _=>{ return -1 } }
}
pub fn payload_pair_mutation(value:i64) i64 {
  original := Box.Value(Pair{a:value,b:2})
  case original { Box.Value *pair => { pair=Pair{a:pair.a+3,b:4} } _=>{} }
  case original { Box.Value pair => { return pair.a+pair.b } _=>{ return -1 } }
}
pub fn assignment_snapshot(value:i64) i64 {
  pair:=Pair{a:value,b:2}
  pair=Pair{a:pair.a+3,b:pair.b+4}
  return pair.a+pair.b
}
fn sum_sink(values:...i64) { total:i64=0
for value in values { total+=value } }
fn any_sink(values:...any) { total:i64=0
for value in values { total+=inspect(value) } }
pub fn pack_defer(value:i64) i64 {
  defer sum_sink(value,2)
  defer any_sink(value,Pair{a:3,b:4})
  return value
}
pub fn pack_defer_panic(value:i64) i64 {
  defer { _=sum(value,2) }
  #panic("original pack failure")
}
extern fn c_sum "backend_variadic_sum"(count: u32, ...) i64
extern fn c_float "backend_variadic_float"(count: u32, ...) f64
pub fn foreign_pack(value: i8) i64 {
  indirect := c_sum
  return c_sum(3,value,#cast(u16, 500),7) + indirect(2,value,9)
}
pub fn foreign_float(value: f32) f64 {
  indirect := c_float
  return c_float(3,value,#cast(f32, 2.5),3.0) + indirect(1,value)
}
pub fn foreign_spills(value:i8) i64 { return c_sum(10,value,1,2,3,4,5,6,7,8,9) }
pub fn foreign_float_spills(value:f32) f64 { return c_float(10,value,1.0,2.0,3.0,4.0,5.0,6.0,7.0,8.0,9.0) }
fn first_failure() i64 { #panic("first variadic argument") }
fn second_failure() i64 { #panic("second variadic argument") }
pub fn pack_order() i64 { return sum(first_failure(),second_failure()) }
pub fn any_order() i64 { return mixed(first_failure(),second_failure()) }
'''
PROVIDER = '''
#include <stdint.h>
#include <stdarg.h>
int64_t backend_variadic_sum(uint32_t count, ...) {
  va_list args; va_start(args,count); int64_t sum=0;
  for(uint32_t i=0;i<count;i++) sum+=va_arg(args,int);
  va_end(args); return sum;
}
double backend_variadic_float(uint32_t count, ...) {
  va_list args; va_start(args,count); double sum=0;
  for(uint32_t i=0;i<count;i++) sum+=va_arg(args,double);
  va_end(args); return sum;
}
'''

def run(args):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, (args, result.returncode, result.stdout, result.stderr)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--oracle-only', action='store_true')
    args = parser.parse_args()
    checks = panics = 0
    with tempfile.TemporaryDirectory(prefix='dyn-backend-features-') as directory:
        root = Path(directory)
        source = root / 'main.dyn'
        source.write_text(SOURCE)
        provider = root / 'provider.c'
        provider.write_text(PROVIDER)
        provider_obj = root / 'provider.o'
        run([*CC,'-fPIC','-c',provider,'-o',provider_obj])
        for mode in ('debug','release'):
            oracle = root / (mode + '-compiler.so')
            run([DYN,'build',root,'--shared','--'+mode,'--no-cache','--jobs','1',
                 '--link',provider_obj,'--output',oracle])
            paths = [oracle]
            if not args.oracle_only:
                obj = root / (mode+'.o')
                run([BUILD/'scalar-backend',*(['--debug'] if mode == 'debug' else []),source,obj])
                symbols = subprocess.check_output(['readelf','-Ws',str(obj)],text=True)
                for symbol in ('small_global','signed_global'):
                    row = next(line.split() for line in symbols.splitlines() if line.split() and line.split()[-1] == symbol)
                    assert row[2] == '1', (symbol,row)
                runtime = root / 'runtime.o'
                support = root / 'support.o'
                run([*CC,'-fPIC','-DDYN_SHARED','-c',ROOT/'runtime/linux_x86_64_start.S','-o',runtime])
                # Match the assembly runtime's current unwind ABI. The Python
                # values and compiler/panic comparisons remain independent.
                run([sys.executable,ROOT/'tools/build-native-support.py','--compiler',DYN,
                     '--target','x86_64-linux','--output',support])
                native = root / (mode+'-native.so')
                run([*CC,'-shared','-Wl,--no-undefined',obj,runtime,support,provider_obj,'-lm','-o',native])
                paths.append(native)
            for path in paths:
                library = ctypes.CDLL(str(path))
                for name,ctype,values,expected in (
                    ('plain',ctypes.c_uint8,[0,1],lambda x:11+11*x),
                    ('signed_tag',ctypes.c_int64,[-128,127],lambda x:x),
                    ('small_global_set',ctypes.c_uint8,[0,1],lambda x:x),
                    ('signed_global_set',ctypes.c_int64,[-128,127],lambda x:x),
                    ('wide_tag',ctypes.c_uint64,[0,2**64-1],lambda x:ctypes.c_int64(x).value),
                    ('payload',ctypes.c_int64,[-100,0,100],lambda x:x+3),
                    ('aggregate_payload',ctypes.c_int64,[-100,0,100],lambda x:x+7),
                    ('boxed',ctypes.c_int64,[-100,0,100],lambda x:x),
                    ('boxed_pair',ctypes.c_int64,[-100,0,100],lambda x:x+7),
                    ('boxed_array',ctypes.c_int64,[-100,0,100],lambda x:x+7),
                    ('boxed_enum',ctypes.c_int64,[-100,0,100],lambda x:x),
                    ('boxed_float',ctypes.c_double,[-100.5,0,100.5],int),
                    ('boxed_identity',ctypes.c_uint8,[0,255],lambda x:-1),
                    ('boxed_bool',ctypes.c_bool,[False,True],int),
                    ('typed_pack',ctypes.c_int64,[-100,0,100],lambda x:x+5),
                    ('any_pack',ctypes.c_int64,[-100,0,100],lambda x:x+9),
                    ('native_spills',ctypes.c_int64,[-100,0,100],lambda x:x+38),
                    ('native_aggregate',ctypes.c_int64,[-100,0,100],lambda x:x+9),
                    ('payload_copy',ctypes.c_int64,[-100,0,100],lambda x:x),
                    ('payload_pair_mutation',ctypes.c_int64,[-100,0,100],lambda x:x+7),
                    ('assignment_snapshot',ctypes.c_int64,[-100,0,100],lambda x:x+9),
                    ('pack_defer',ctypes.c_int64,[-100,0,100],lambda x:x),
                    ('foreign_pack',ctypes.c_int8,[-128,0,127],lambda x:2*x+516),
                    ('foreign_float',ctypes.c_float,[-2.5,0,1.25],lambda x:2*x+5.5),
                    ('foreign_spills',ctypes.c_int8,[-128,0,127],lambda x:x+45),
                    ('foreign_float_spills',ctypes.c_float,[-2.5,0,1.25],lambda x:x+45),
                ):
                    function = getattr(library,name)
                    function.argtypes = [ctype]
                    function.restype = ctypes.c_double if name.startswith('foreign_float') else ctypes.c_int64
                    for value in values:
                        actual = function(value)
                        assert actual == expected(value), (mode,path,name,value,actual,expected(value))
                        checks += 1
            libraries = [ctypes.CDLL(str(path)) for path in paths]
            for caller in libraries:
                for callee in libraries:
                    for wrapper,identity,extra in (('enum_cross','enum_identity',0),('box_cross','box_identity',7)):
                        function = getattr(caller,wrapper)
                        function.argtypes = [ctypes.c_void_p,ctypes.c_int64]
                        function.restype = ctypes.c_int64
                        for value in (-100,0,100):
                            actual = function(ctypes.cast(getattr(callee,identity),ctypes.c_void_p),value)
                            assert actual == value+extra, (mode,wrapper,value,actual)
                            checks += 1
            for name,value,message in (
                ('plain',255,'runtime check failed (enum.cast.ok) in plain'),
                ('signed_tag',128,'runtime check failed (enum.cast.ok) in signed_tag'),
                ('wrong_signed_tag',-1,'runtime check failed (enum.cast.ok) in wrong_signed_tag'),
                ('payload',2**63-1,'runtime check failed (overflow.ok) in payload'),
                ('typed_pack',2**63-1,'runtime check failed (overflow.ok) in sum'),
                ('any_pack',2**63-1,'runtime check failed (overflow.ok) in mixed'),
                ('pack_order',None,'first variadic argument'),
                ('any_order',None,'first variadic argument'),
                ('pack_defer_panic',2**63-1,'runtime check failed (overflow.ok) in sum'),
            ):
                outputs = []
                for path in paths:
                    code = ('import ctypes,sys; lib=ctypes.CDLL(sys.argv[1]); '
                            'f=getattr(lib,sys.argv[2]); f.restype=ctypes.c_int64; '
                            'f.argtypes=[] if sys.argv[3]=="None" else [ctypes.c_int64]; '
                            'f(*([] if sys.argv[3]=="None" else [int(sys.argv[3])]))')
                    result = subprocess.run([sys.executable,'-c',code,str(path),name,str(value)],
                                            capture_output=True,text=True,timeout=10)
                    assert result.returncode == 101, (mode,name,path,result.returncode,result.stderr)
                    assert result.stderr.splitlines()[0] == message, (mode,name,result.stderr)
                    outputs.append((result.stdout,result.stderr))
                    panics += 1
                assert len(set(outputs)) == 1, (mode,name,outputs)
    print(f'PASS {checks} enum/any/variadic values; {panics} panics ({"oracle only" if args.oracle_only else "compiler and standalone backend"})')

if __name__ == '__main__':
    main()
