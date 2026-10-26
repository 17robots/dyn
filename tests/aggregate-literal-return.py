#!/usr/bin/env python3
"""Scalar sret literals: independent C byte/alias/effect oracle and code shape.

Uses an assembly ABI shim to deliberately overlap the hidden return pointer
with an input; ordinary C struct-return calls cannot express that contract.
"""
import os
from pathlib import Path
import platform
import re
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    print('SKIP aggregate literal return oracle: requires x86-64 Linux')
    raise SystemExit(0)

SOURCE = r'''
use "std/io"
enum Error { None, Bad }
struct Result { error:Error, code:i64, memory:rawptr, size:u64, ok:bool }
struct Triple { a:u64, b:u64, c:u64 }
struct Defaults { a:u64=10, b:u64=20, c:u64 }
struct Mixed { a:f64, b:u64 }
struct Floats { a:f64, b:f32, c:u64 }
struct Nested { a:[3]u64, text:[]const u8 }
extern fn mark(x:u64) u64
extern fn mutate(p:*u64) u64
extern fn oracle() i32
pub fn allocation(memory:rawptr,size:u64) Result {
  return Result{memory:memory,size:size,ok:true}
}
pub fn overlap(p:*Triple) Triple { return Triple{a:p.b,b:p.c,c:p.a} }
pub fn effects(p:*u64) Triple { return Triple{c:p.*,a:mutate(p),b:p.*} }
pub fn defaults() Defaults { return Defaults{b:mark(3),c:mark(4)} }
pub fn cleanup(p:*Triple) Triple {
  defer { p.a=99
  p.b=98
  p.c=97 }
  return Triple{a:p.b,b:p.c,c:p.a}
}
pub fn mixed(x:f64,y:u64) Mixed { return Mixed{a:x,b:y} }
pub fn floats(x:f64,y:f32,z:u64) Floats { return Floats{a:x,b:y,c:z} }
pub fn nested() Nested { return Nested{a:[7,8,9],text:"ok"} }
pub fn raw() [3]u64 { return [7,8,9] }
pub fn desc() []const u8 { return "ok" }
pub fn checked(p:*u64,q:*u64) Triple { return Triple{a:p.*,b:q.*,c:mark(5)} }
fn main() { r:=oracle()
if r!=0 { _=io.println(io.stderr(),"oracle {}",r)
#panic("C aggregate oracle") } }
'''

C_SOURCE = r'''
#include <stdint.h>
#include <stddef.h>
static void fill(void *p,unsigned char c,unsigned long n) { unsigned char *b=p; for(unsigned long i=0;i<n;i++) b[i]=c; }
static int different(const void *a,const void *b,unsigned long n) { const unsigned char *x=a,*y=b; for(unsigned long i=0;i<n;i++) if(x[i]!=y[i]) return 1; return 0; }
typedef struct { uint32_t error; int64_t code; void *memory; uint64_t size; _Bool ok; } Result;
typedef struct { uint64_t a,b,c; } Triple;
typedef struct { double a; uint64_t b; } Mixed;
typedef struct { double a; float b; uint64_t c; } Floats;
typedef struct { const char *p; uint64_t n; } Slice;
typedef struct { uint64_t a[3]; Slice text; } Nested;
extern Result allocation(void*,uint64_t);
extern Triple effects(uint64_t*),defaults(void),cleanup(Triple*);
extern Mixed mixed(double,uint64_t);
extern Floats floats(double,float,uint64_t);
extern Nested nested(void);
extern Slice desc(void);
extern void invoke_raw(Triple*),invoke_cleanup(Triple*);
/* Dyn raw arrays use three result words here, independently of C structs. */
__asm__(".text\n.globl invoke_raw\ninvoke_raw:\npush %rbx\nmov %rdi,%rbx\ncall raw\n"
        "mov %rax,(%rbx)\nmov %rdx,8(%rbx)\nmov %rcx,16(%rbx)\npop %rbx\nret\n"
        ".globl invoke_cleanup\ninvoke_cleanup:\nmov %rdi,%rsi\njmp cleanup\n");
extern void invoke_overlap(Triple*);
__asm__(".text\n.globl invoke_overlap\ninvoke_overlap:\nmov %rdi,%rsi\njmp overlap\n");
extern void invoke_effects(Triple*);
__asm__(".text\n.globl invoke_effects\ninvoke_effects:\nmov %rdi,%rsi\njmp effects\n");
static uint64_t log_value;
uint64_t mark(uint64_t x) { if(x==5) __builtin_trap(); log_value=log_value*10+x; return x*10; }
uint64_t mutate(uint64_t *p) { uint64_t old=*p; *p=old+1; return old+100; }
int32_t oracle(void) {
  _Static_assert(sizeof(Result)==40,"result layout");
  /* Compare every byte, including implicit fields and internal/tail padding.
     Force the physical sret buffer through a shim rather than C's unspecified
     padding after struct assignment. */
  Result expected; fill(&expected,0,sizeof expected);
  expected.memory=(void*)(uintptr_t)0x12340; expected.size=123; expected.ok=1;
  extern void invoke_allocation(Result*,void*,uint64_t);
  Result actual; fill(&actual,0xa5,sizeof actual);
  invoke_allocation(&actual,expected.memory,expected.size);
  if (different(&actual,&expected,sizeof actual)) return 1;
  Triple t={11,22,33}; invoke_overlap(&t);
  if(t.a!=22 || t.b!=33 || t.c!=11) return 2;
  uint64_t n=7; t=effects(&n);
  if(n!=8 || t.a!=107 || t.b!=8 || t.c!=7) return 3;
  t.a=7; invoke_effects(&t);
  if(t.a!=107 || t.b!=8 || t.c!=7) return 8;
  log_value=0; t=defaults();
  if(log_value!=34 || t.a!=10 || t.b!=30 || t.c!=40) return 4;
  Triple input={1,2,3}; t=cleanup(&input);
  if(t.a!=2 || t.b!=3 || t.c!=1 || input.a!=99 || input.b!=98 || input.c!=97) return 5;
  t.a=1; t.b=2; t.c=3; invoke_cleanup(&t);
  if(t.a!=2 || t.b!=3 || t.c!=1) return 10;
  Mixed m=mixed(1.25,42); if(m.a!=1.25 || m.b!=42) return 6;
  Floats f=floats(1.25,2.5f,42); if(f.a!=1.25 || f.b!=2.5f || f.c!=42) return 9;
  Nested nest=nested();
  if(nest.a[0]!=7 || nest.a[1]!=8 || nest.a[2]!=9 || nest.text.n!=2 || different(nest.text.p,"ok",2)) return 7;
  invoke_raw(&t); if(t.a!=7 || t.b!=8 || t.c!=9) return 11;
  Slice text=desc(); if(text.n!=2 || different(text.p,"ok",2)) return 12;
  return 0;
}
/* All three registers already match the actual SysV sret entry. */
__asm__(".text\n.globl invoke_allocation\ninvoke_allocation:\njmp allocation\n");
'''


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, timeout=120, **kwargs)


with tempfile.TemporaryDirectory(prefix='dyn-aggregate-literal-') as directory:
    work = Path(directory)
    source = work/'source'
    source.mkdir()
    (source/'main.dyn').write_text(SOURCE)
    (work/'oracle.c').write_text(C_SOURCE)
    run([*shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-O2', '-fno-stack-protector', '-ffreestanding', '-c',
         work/'oracle.c', '-o', work/'oracle.o'])
    for mode in ('ssa', 'tree'):
        env = dict(os.environ, DYN_NO_SSA='1' if mode == 'tree' else '0')
        output = work/mode
        run([DYN, 'build', source, '--release', '--no-cache', '--emit-object',
             '--link', work/'oracle.o', '--output', output], env=env)
        run([output])
        if mode == 'ssa':
            assembly = subprocess.check_output(['objdump', '-d', '-Mintel', str(output)+'.o'], text=True)
            body = re.search(r'<allocation>:\n(.*?)(?=\n\n|\Z)', assembly, re.S).group(1)
            # A scalar-only constructor has no reason to read aggregate bytes
            # back from a stack result. Allow the hidden-pointer frame spill,
            # but allow at most one memory read (that pointer reload).
            instructions = [line.split('\t')[-1].strip() for line in body.splitlines() if '\t' in line]
            reads = [ins for ins in instructions if re.match(r'(mov\w*|vmov\w*)\s+[^,]+,.*\[', ins)]
            assert len(reads) <= 1, body
            assert not any(re.match(r'(call|rep\s+movs)', ins) for ins in instructions), body
            # Stack writes of aggregate payload would reintroduce construction
            # followed by a copy even if that copy were unrolled/vectorized.
            stack_stores = [ins for ins in instructions if re.match(r'mov\w*\s+.*\[(?:r[bs]p)', ins)]
            assert len(stack_stores) <= 1, body
    # Pointer checks retain source initializer order, before later effects.
    # mark(5) traps independently, so these must report a pointer failure first.
    for arguments in ('nil,nil', 'nil,&x', '&x,nil'):
        failures = []
        for mode in ('ssa', 'tree'):
            env = dict(os.environ, DYN_NO_SSA='1' if mode == 'tree' else '0')
            panic = SOURCE[:SOURCE.index('fn main()')] + 'fn main() { x:u64=1\n_=checked('+arguments+') }\n'
            (source/'main.dyn').write_text(panic)
            output = work/('panic-'+mode)
            run([DYN, 'build', source, '--release', '--no-cache', '--link', work/'oracle.o', '--output', output], env=env)
            result = subprocess.run([str(output)], text=True, capture_output=True, timeout=20)
            assert result.returncode != 0 and 'pointer.nonnull.ok' in result.stderr, result
            failures.append((result.returncode, result.stderr))
        assert failures[0] == failures[1], failures
print('PASS aggregate literal returns: C bytes, overlap, effects, defaults, defers, ABI fallbacks and emitted stores')
