#!/usr/bin/env python3
"""Fresh aggregate call destinations avoid copies; observable locals retain snapshots."""
import os
from pathlib import Path
import platform
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    print('SKIP aggregate call destinations: requires x86-64 Linux')
    raise SystemExit(0)

SOURCE = r'''
enum Error { None, Bad }
struct Result { error:Error, code:i64, memory:rawptr, size:u64, ok:bool }
extern fn produce(size:u64) Result
extern fn observe(p:*Result) u64
extern fn oracle() i32
pub fn fresh(size:u64) u64 {
  r:=produce(size)
  if !r.ok { return 0 }
  return r.size
}
pub fn exposed(size:u64) u64 {
  r:=produce(size)
  return observe(&r)
}
pub fn assigned(size:u64) u64 {
  r:=produce(1)
  r=produce(size)
  return r.size
}
pub fn looped(size:u64) u64 {
  total:u64=0
  for i in 0..size {
    r:=produce(i)
    if r.ok { total+=r.size }
  }
  return total
}
pub fn cleanup(size:u64,p:*u64) u64 {
  defer { p.*+=1 }
  r:=produce(size)
  if !r.ok { return 0 }
  return r.size
}
fn main() { if oracle()!=0 { #panic("aggregate call destination oracle") } }
'''
C_SOURCE = r'''
#include <stdint.h>
typedef struct { uint32_t error; int64_t code; void *memory; uint64_t size; _Bool ok; } Result;
_Static_assert(sizeof(Result)==40,"allocator result layout");
static uint64_t calls;
Result produce(uint64_t size) {
  ++calls;
  Result r={0}; r.size=size; r.ok=size!=7;
  r.error=r.ok?0:1; r.code=r.ok?0:-1; r.memory=r.ok?(void*)(uintptr_t)0x12340:0;
  return r;
}
uint64_t observe(Result *r) { return r->size+r->ok; }
extern uint64_t fresh(uint64_t),exposed(uint64_t),assigned(uint64_t),looped(uint64_t),cleanup(uint64_t,uint64_t*);
int32_t oracle(void) {
  calls=0;
  if(fresh(42)!=42 || fresh(7)!=0 || calls!=2) return 1;
  if(exposed(42)!=43 || exposed(7)!=7) return 2;
  if(assigned(42)!=42 || assigned(7)!=7) return 3;
  if(looped(10)!=38) return 4;
  uint64_t n=0;
  if(cleanup(42,&n)!=42 || n!=1 || cleanup(7,&n)!=0 || n!=2) return 5;
  return 0;
}
'''


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, timeout=120, **kwargs)


with tempfile.TemporaryDirectory(prefix='dyn-call-destination-') as directory:
    work = Path(directory)
    source = work/'source'
    source.mkdir()
    (source/'main.dyn').write_text(SOURCE)
    (work/'oracle.c').write_text(C_SOURCE)
    run([os.environ.get('CC', 'cc'), '-std=c11', '-O2', '-fno-stack-protector', '-ffreestanding', '-c', work/'oracle.c', '-o', work/'oracle.o'])
    for mode in ('ssa', 'tree'):
        env = dict(os.environ, DYN_NO_SSA='1' if mode == 'tree' else '0')
        output = work/mode
        run([DYN, 'build', source, '--release', '--no-cache', '--emit-object',
             '--link', work/'oracle.o', '--output', output], env=env)
        run([output])
        if mode == 'ssa':
            assembly = subprocess.check_output(['objdump', '-d', '-Mintel', str(output)+'.o'], text=True)
            body = re.search(r'<fresh>:\n(.*?)(?=\n\n|\Z)', assembly, re.S).group(1)
            instructions = [line.split('\t')[-1].strip() for line in body.splitlines() if '\t' in line]
            # Exactly two payload reads: success flag and size. A whole 40-byte
            # result copy adds five word reads, regardless of frame offsets.
            reads = [ins for ins in instructions if re.match(r'(mov\w*|vmov\w*)\s+[^,]+,.*\[', ins)]
            assert len(reads) <= 2, body
            assert not any(re.match(r'rep\s+movs', ins) for ins in instructions), body
            # Address exposure and reassignment retain the snapshot path.
            for name in ('exposed', 'assigned'):
                control = re.search(r'<'+name+r'>:\n(.*?)(?=\n\n|\Z)', assembly, re.S).group(1)
                control_reads = re.findall(r'\tmov\w*\s+[^,\n]+,[^\n]*\[', control)
                assert len(control_reads) >= 5, control
print('PASS aggregate call destinations: copy shape, failure, exposed locals, assignments, loops and defers')
