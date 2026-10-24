#!/usr/bin/env python3
"""Opaque numerical inputs prove native square root and Wasm math lowering."""
import math
import ctypes
import ctypes.util
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
def bits(x): return struct.unpack('<Q',struct.pack('<d',x))[0]
def number(x): return struct.unpack('<d',struct.pack('<Q',x))[0]
def run(args,**kw):
    p=subprocess.run(list(map(str,args)),capture_output=True,timeout=120,**kw)
    assert p.returncode==0,(args,p.returncode,p.stdout,p.stderr)
    return p
rng=random.Random(0x53515254)
inputs=[0,1,2,0x000fffffffffffff,0x0010000000000000,0x3ff0000000000000,0x4000000000000000,0x7fefffffffffffff,0x8000000000000000,0x7ff0000000000000]
inputs += [rng.getrandbits(63)%0x7ff0000000000000 for _ in range(512)]
checks=[]
for x in inputs:
    expected=bits(math.sqrt(number(x)))
    checks.append(f'if #bitcast(u64,square(#bitcast(f64,opaque({x})))) != {expected} {{ #panic("sqrt bits") }}')
checks += ['if !m.is_nan(square(#bitcast(f64,opaque(13830554455654793216)))) { #panic("sqrt negative") }',
           'if !m.is_nan(square(#bitcast(f64,opaque(9221120237041090626)))) { #panic("sqrt NaN") }',
           'if fake.sqrt64(2.0)!=9.0 { #panic("shadow recognized") }',
           'if square(tick())!=3.0 || calls!=1 { #panic("operand evaluated twice") }']
libm=ctypes.CDLL(ctypes.util.find_library('m') or None)
libm.fma.argtypes=[ctypes.c_double]*3; libm.fma.restype=ctypes.c_double
libm.fmaf.argtypes=[ctypes.c_float]*3; libm.fmaf.restype=ctypes.c_float
for x in (0,0x8000000000000000,1,0x7ff0000000000000,0x7ff0000000000042,0xfff8000000000042):
    for y in (0,0x8000000000000000,0xbff0000000000000):
        expected=(x&0x7fffffffffffffff)|(y&0x8000000000000000)
        checks.append(f'if #bitcast(u64,signed(#bitcast(f64,opaque({x})),#bitcast(f64,opaque({y}))))!={expected} {{ #panic("copysign bits") }}')
for width,oracle in ((64,libm.fma),(32,libm.fmaf)):
    pack='<d' if width==64 else '<f'; integer='<Q' if width==64 else '<I'
    def narrow(x): return struct.unpack(pack,struct.pack(pack,x))[0]
    def integer_bits(x): return struct.unpack(integer,struct.pack(pack,x))[0]
    triples=[(1+2**(-27 if width==64 else -13),1-2**(-27 if width==64 else -13),-1),
             (0.0,-1.0,-0.0),(math.inf,0.0,1.0),
             (number(0x7fefffffffffffff) if width==64 else float.fromhex('0x1.fffffep127'),2.0,
              -number(0x7fefffffffffffff) if width==64 else -float.fromhex('0x1.fffffep127'))]
    triples += [tuple(math.ldexp(rng.uniform(-2,2),rng.randrange(-40,40)) for _ in range(3)) for _ in range(64)]
    for triple in triples:
        triple=tuple(narrow(x) for x in triple)
        value=oracle(*triple)
        arguments=','.join(f'#bitcast(f{width},'+(f'opaque({integer_bits(x)})' if width==64 else f'#cast(u32,opaque({integer_bits(x)}))')+')' for x in triple)
        call=f'fused{width}({arguments})'
        condition=f'!m.is_nan({call})' if math.isnan(value) else f'#bitcast(u{width},{call})!={integer_bits(value)}'
        checks.append(f'if {condition} {{ #panic("fused f{width} bits") }}')
for name in ('floor','ceil','trunc','round'):
    oracle=getattr(libm,name); oracle.argtypes=[ctypes.c_double]; oracle.restype=ctypes.c_double
    for x in (0.0,-0.0,1.5,-1.5,2.5,-2.5,number(1),-number(1),number(0x7fefffffffffffff),math.inf,-math.inf,math.nan):
        value=oracle(x)
        call=f'rounded_{name}(#bitcast(f64,opaque({bits(x)})))'
        condition=f'!m.is_nan({call})' if math.isnan(value) else f'#bitcast(u64,{call})!={bits(value)}'
        checks.append(f'if {condition} {{ #panic("{name} bits") }}')
checks.append('trace=0 if fused64(mark(1),mark(2),mark(3))!=5.0 || trace!=123 { #panic("fused argument order") }')
params=','.join(f'p{i}:f64' for i in range(30))
terms=[f'm.fma64(p{i},p{i+1},p{i+2})' for i in range(27,-1,-3)]+[f'p{i}' for i in range(30)]
pressure='pub fn pressure('+params+') f64 { return '+'+'.join(terms)+' }\n'
values=list(range(1,31))
expected=sum(values[i]*values[i+1]+values[i+2] for i in range(27,-1,-3))+sum(values)
args=','.join(f'#bitcast(f64,opaque({bits(float(v))}))' for v in values)
checks.append(f'if pressure({args})!={expected}.0 {{ #panic("fused spills") }}')
SOURCE='''use "std/math" m
use "fake" fake
extern fn opaque "dyn_math_opaque"(x:u64) u64
calls:i32
trace:i32
fn mark(x:i32) f64 { trace=trace*10+x return #cast(f64,x) }
fn tick() f64 { calls+=1 return 9.0 }
pub fn square(x:f64) f64 { return m.sqrt64(x) }
pub fn signed(x,y:f64) f64 { return m.copysign64(x,y) }
pub fn fused64(x,y,z:f64) f64 { return m.fma64(x,y,z) }
pub fn fused32(x,y,z:f32) f32 { return m.fma(x,y,z) }
'''+''.join(f'pub fn rounded_{name}(x:f64)f64 {{ return m.{name}64(x) }}\n' for name in ('floor','ceil','trunc','round'))+pressure+'fn main() {\n'+ '\n'.join(checks)+'\n}\n'
WASM='''use "std/math" m
pub fn square(x:f64) f64 { return m.sqrt64(x) }
pub fn floor(x:f64) f64 { return m.floor64(x) }
pub fn ceil(x:f64) f64 { return m.ceil64(x) }
pub fn trunc(x:f64) f64 { return m.trunc64(x) }
pub fn sign(x:f64,y:f64) f64 { return m.copysign64(x,y) }
pub fn round(x:f64) f64 { return m.round64(x) }
'''
with tempfile.TemporaryDirectory(prefix='dyn-math-lowering-') as directory:
    work=Path(directory); project=work/'project';project.mkdir()
    (project/'main.dyn').write_text(SOURCE)
    (project/'fake').mkdir();(project/'fake/fake.dyn').write_text('pub fn sqrt64(x:f64) f64 { return x+7.0 }\n')
    cc=shutil.which('cc')
    assert cc,'C compiler required for opaque-input oracle'
    (work/'opaque.c').write_text('typedef unsigned long long uint64_t;\nuint64_t dyn_math_opaque(uint64_t x) { volatile uint64_t y=x; return y; }\n')
    run([cc,'-c',work/'opaque.c','-o',work/'opaque.o'])
    for mode,cpu in [('debug','generic'),('release','generic'),('debug','native'),('release','native')]:
        for tree in (False,True):
            env=dict(os.environ,DYN_SDK=str(ROOT))
            if tree: env['DYN_NO_SSA']='1'
            else: env.pop('DYN_NO_SSA',None)
            flags=['--'+mode,'--cpu',cpu]
            if mode=='release': flags+=['--opt-remarks']
            result=run([DYN,'build',project,*flags,'--quiet','--no-cache','--link',work/'opaque.o','--output',work/'test'],env=env)
            if mode=='release' and not tree:
                assert all((name+': SSA code generation').encode() in result.stderr for name in ('square','signed','fused64','fused32','pressure')),result.stderr
            run([work/'test'])
    clang=shutil.which('clang')
    for target,triple,emulator,extra in [('aarch64-linux','aarch64-linux-gnu','qemu-aarch64',[]),('riscv64-linux','riscv64-linux-gnu','qemu-riscv64',['-march=rv64g'])]:
        runner=shutil.which(emulator)
        if not clang or not runner:
            print('SKIP math-lowering '+target+': clang or emulator unavailable')
            continue
        obj=work/(target+'.o')
        run([clang,'--target='+triple,*extra,'-c',work/'opaque.c','-o',obj])
        for tree in (False,True):
            env=dict(os.environ,DYN_SDK=str(ROOT))
            if tree: env['DYN_NO_SSA']='1'
            else: env.pop('DYN_NO_SSA',None)
            result=run([DYN,'build',project,'--target',target,'--release','--opt-remarks','--no-cache','--quiet','--link',obj,'--output',work/'cross'],env=env)
            if not tree: assert all((name+': SSA code generation').encode() in result.stderr for name in ('square','signed','fused64','fused32','pressure')),result.stderr
            run([runner,work/'cross'])
        print('PASS math-lowering '+target+' SSA/tree IEEE oracle')
    # New x86 opcode must be visible in assembly, rather than an opaque byte comment.
    assembly=work/'square'
    run([DYN,'build',project,'--release','--shared','--no-link','--emit-object','--emit-asm','--target','x86_64-linux','--output',assembly],env=dict(os.environ,DYN_SDK=str(ROOT)))
    assert b'sqrtsd' in assembly.with_suffix('.s').read_bytes(),'native square-root instruction missing'
    generic=assembly.with_suffix('.s').read_bytes()
    assert b'vfmadd213' not in generic and b'roundsd' not in generic,'optional instructions escaped generic feature gate'
    selected=run([DYN,'build',project,'--release','--cpu','native','--opt-remarks','--shared','--no-link','--emit-object','--emit-asm','--target','x86_64-linux','--output',assembly],env=dict(os.environ,DYN_SDK=str(ROOT)))
    native=assembly.with_suffix('.s').read_bytes()
    if b'+fma fused multiply-add' in selected.stderr:
        assert b'vfmadd213sd' in native and b'vfmadd213ss' in native,'selected FMA did not lower'
    if b'+sse4.1 scalar rounding' in selected.stderr:
        assert b'roundsd' in native,'selected SSE4.1 did not lower'

    node=shutil.which('node')
    if node:
        (project/'main.dyn').write_text(WASM)
        js='''const a=require('node:assert/strict');
(async()=>{const e=(await WebAssembly.instantiate(require('node:fs').readFileSync(process.argv[1]))).instance.exports;e.dyn_initialize();
for(const x of [0,-0,1,-1,2,1.5,-1.5,Infinity,-Infinity,NaN,Number.MIN_VALUE,Number.MAX_VALUE]){
for(const [n,f] of [['square',Math.sqrt],['floor',Math.floor],['ceil',Math.ceil],['trunc',Math.trunc]])a.ok(Object.is(e[n](x),f(x)),n+' '+x);
for(const y of [0,-0,1,-1])a.ok(Object.is(e.sign(x,y),(Object.is(y,-0)||y<0)?-Math.abs(x):Math.abs(x)));
}a.equal(e.round(1.5),2);a.equal(e.round(-1.5),-2);
})().catch(x=>{console.error(x);process.exit(1)});'''
        for mode in ('debug','release'):
            run([DYN,'build',project,'--target','wasm32-browser','--shared','--'+mode,'--output',work/'test.wasm'],env=dict(os.environ,DYN_SDK=str(ROOT)))
            run([node,'-e',js,work/'test.wasm'])
    else: print('SKIP math-lowering Wasm execution: Node unavailable')
print('PASS math lowering: opaque IEEE sqrt/FMA/rounding oracles, sign bits, evaluation order, spills, shadow names, SSA/tree; Wasm where available')
