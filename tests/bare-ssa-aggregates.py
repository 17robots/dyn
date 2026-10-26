#!/usr/bin/env python3
"""SSA32 local aggregates: 36 hard-target guests plus four soft SSA/tree guests.

ROOT selects the compiler directory; DYN and CLANG override compilers.
DYN_QEMU_RISCV32 / DYN_QEMU_ARM are shell-split command prefixes.
LLVM_OBJDUMP overrides llvm-objdump for the RV32 store-width assertion.
Container wrappers must mount TMPDIR at the same path and bound guest lifetime
(e.g. timeout 20 qemu-system-arm). Host execution is bounded too. All generated
files use TemporaryDirectory and respect TMPDIR.
"""
import importlib.util
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(os.environ.get('ROOT', Path(__file__).resolve().parents[1])).resolve()
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
OBJDUMP = shlex.split(os.environ.get('LLVM_OBJDUMP', 'llvm-objdump'))
CLANG = shlex.split(os.environ.get('CLANG', 'clang'))

def sibling(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT/'tests'/f'{name}.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

b = sibling('bare-ssa')
calls = sibling('bare-ssa-calls')

SOURCE = r'''
use "std/io"
struct Inner { x:u32,y:u64 }
struct Outer { pre:u32,inner:Inner,post:u32 }
struct Descs { pre:u32,text:[]const u8,mid:u32,view:[]u8,post:u32 }
struct Box { pre:u64,value:any,post:u64 }
extern fn verifydescs(p:*Descs) u32
extern fn verifybox(p:*Box) u64
pub fn arrays(i:usize,x:u32) u32 { a:[8]u32=[]
a[i]=x
b:=a
b[(i+1)%8]=7
return a[i]+b[i]+b[(i+1)%8] }
pub fn nested(x:u64) u64 { a:=Outer{pre:19,inner:Inner{x:23,y:x},post:29}
p:=&a
p.inner.y=p.inner.y+1
return a.inner.y+#cast(u64,a.pre+a.inner.x+a.post) }
pub fn descs(i:usize) u32 { a:[8]u8=[10,11,12,13,14,15,16,17]
d:=Descs{pre:101,text:"abcdef",mid:103,view:a[..],post:107}
p:=&d
p.text="zyxwvu"
p.view=a[1..7]
return verifydescs(p)+#cast(u32,p.text[i])+#cast(u32,p.view[i])+#cast(u32,#len(p.text)+#len(p.view))+p.pre+p.mid+p.post }
pub fn substr(i:usize) u32 { s:="abcdef"
t:=s[1..5]
return #cast(u32,t[i])+#cast(u32,#len(t)) }
pub fn boxed(x:u64) u64 { a:=Box{pre:71,value:x,post:73}
p:=&a
check:=verifybox(p)
b:=p.value
case b { is u64 y=>{ return y+a.pre+a.post+check } _=>{return 0} } }
pub fn copybytes(dst:*[33]u8,src:*[33]u8) { dst.*=src.* }
pub fn zerobytes(dst:*[33]u8) { dst.*=[] }
pub fn zeroforward(dst:*[8]u8) { a:[8]u8=[]
dst.*=a }
pub fn zerochain(dst:*[8]u8) { a:[8]u8=[]
b:=a
dst.*=b }
pub fn zerocopy(dst:*[0]u8,src:*[0]u8) { dst.*=src.*
dst.*=[] }
pub fn readptr(p:*u64) u64 { return p.* }
pub fn indexfail(i:usize) u8 { a:[3]u8=[1,2,3]
return a[i] }
pub fn slicefail(a:usize,b:usize) usize { x:="abcdef"
return #len(x[a..b]) }
extern fn oracle() i32
fn main() { n:=oracle()
if n!=0 { _=io.println(io.stdout(),"BAD {}",n)
#panic("oracle") }
_=io.write_all(io.stdout(),"LOCALS OK\n") }
'''

C_SOURCE = r'''
typedef unsigned long long U; typedef unsigned W;
extern W arrays(W,W),descs(W),substr(W);extern U nested(U),boxed(U);extern void copybytes(void*,void*),zerobytes(void*),zerocopy(void*,void*),zeroforward(void*);
extern void zerochain(void*);
W verifydescs(void *p) {
 struct D { W pre; const unsigned char *text; W len,mid; unsigned char *view; W count,post; };struct D *d=p;
 return d->pre!=101 || d->len!=6 || d->mid!=103 || d->count!=6 || d->post!=107 || d->text[0]!='z' || d->view[0]!=11 ? 10000 : 0;
}
U verifybox(void *p) {
 struct B { U pre,tag; void *data; W pad; U post; };struct B *b=p;
 return b->pre!=71 || b->post!=73 || *(U*)b->data!=0x123456789abcdefULL ? 10000 : 0;
}
int oracle(void) {
#if defined(__arm__)
 /* Make a widened store to the odd byte-array destination fault on Thumb. */
 volatile W *ccr=(volatile W*)0xe000ed14;
 *ccr |= 1u<<3;
 __asm__ volatile("dsb sy\n isb sy" ::: "memory");
 if(!(*ccr & (1u<<3))) return 8;
#endif
 for(W i=0;i<8;i++) if(arrays(i,100+i)!=207+2*i) return 1;
 if(nested(0x123456789abcdefULL)!=0x123456789abce37ULL) return 2;
 for(W i=0;i<4;i++) if(descs(i)!=456 || substr(i)!=102+i) return 3;
 if(boxed(0x123456789abcdefULL)!=0x123456789abce7fULL) return 4;
 unsigned char a[96] __attribute__((aligned(8))),b[96];
 for(W delta=0;delta<12;delta++) for(W rev=0;rev<2;rev++) {
  for(W i=0;i<96;i++) a[i]=b[i]=i;
  W d=rev?16:16+delta,s=rev?16+delta:16;
  if(d>s) { for(W i=33;i-->0;) b[d+i]=b[s+i]; } else { for(W i=0;i<33;i++) b[d+i]=b[s+i]; }
  copybytes(a+d,a+s);for(W i=0;i<96;i++) if(a[i]!=b[i]) return 5;
 }
 for(W i=0;i<96;i++) a[i]=i;
 zerobytes(a+17);for(W i=0;i<96;i++) if(a[i]!=(i>=17 && i<50 ? 0 : i)) return 6;
 for(W i=0;i<96;i++) a[i]=i;
 zerocopy(a+17,a+19);for(W i=0;i<96;i++) if(a[i]!=i)return 7;
 for(W i=0;i<96;i++) a[i]=i;
 zeroforward(a+17);for(W i=0;i<96;i++) if(a[i]!=(i>=17 && i<25 ? 0 : i)) return 9;
 for(W i=0;i<96;i++) a[i]=i;
 zerochain(a+17);for(W i=0;i<96;i++) if(a[i]!=(i>=17 && i<25 ? 0 : i)) return 10;
 return 0;
}
'''

POSITIVE = 'arrays nested descs substr boxed copybytes zerobytes zerocopy zeroforward zerochain readptr indexfail slicefail'.split()
GUARDS = [
    ('null', 'readptr(nil)', 'readptr', 'pointer.nonnull.ok', ''),
    ('align', 'readptr(#cast(*u64,1))', 'readptr', 'pointer.aligned.ok', ''),
    ('index', 'indexfail(3)', 'indexfail', 'index.ok', ''),
    ('indexwide', 'indexfail(4294967295)', 'indexfail', 'index.ok', ''),
    ('sliceorder', 'slicefail(5,2)', 'slicefail', 'slice.order.ok', ''),
    ('slicebounds', 'slicefail(1,7)', 'slicefail', 'slice.bounds.ok', ''),
    ('ordered', 'ordered(3)', 'ordered', 'index.ok', 'MARK 3\n'),
    ('orderedslice', 'sliceorder(7,2)', 'sliceorder', 'slice.order.ok', 'MARK 7\nMARK 2\n'),
]
ORDERED = r'''
pub fn mark(x:usize) usize { _=io.println(io.stdout(),"MARK {}",x)
return x }
pub fn ordered(i:usize) u8 { a:[3]u8=[1,2,3]
return a[mark(i)] }
pub fn sliceorder(a:usize,b:usize) usize { x:="abcdef"
return #len(x[mark(a)..mark(b)]) }
'''


def check_remarks(log, mode, names):
    if mode == 'tree':
        assert 'SSA code generation' not in log, log
        return
    for name in names:
        messages = re.findall(r'^remark: ' + re.escape(name) + r': (.*)$', log, re.M)
        assert any(m.startswith('SSA code generation,') for m in messages), (name, messages, log)
        assert not any('tree emitter' in m for m in messages), (name, messages)


def main():
    names = POSITIVE + ['ordered', 'sliceorder']
    for missing in names:
        log = '\n'.join(f'remark: {name}: SSA code generation, test' for name in names if name != missing)
        try:
            check_remarks(log, 'ssa', names)
        except AssertionError:
            pass
        else:
            raise AssertionError(f'missing named lowering remark accepted: {missing}')
    for label, command in [('DYN', [DYN]), ('CLANG', CLANG)]:
        if not command or not shutil.which(command[0]):
            print(f'SKIP aggregates: {label} executable unavailable: {command}', flush=True)
            return
    completed = 0
    for target, variable, program, flags, board in b.TARGETS:
        qemu = shlex.split(os.environ.get(variable, '')) or [program]
        if not shutil.which(qemu[0]):
            print(f'SKIP {target} and soft: {qemu[0]} unavailable; set {variable}', flush=True)
            continue
        with tempfile.TemporaryDirectory(prefix='dyn-ssa-aggregates-') as temporary:
            work = Path(temporary)
            project = work/'source'
            project.mkdir()
            (work/'oracle.c').write_text(C_SOURCE)
            obj = work/'oracle.o'
            subprocess.run([*CLANG, *flags, '-ffreestanding', '-fno-stack-protector',
                            '-O2', '-c', str(work/'oracle.c'), '-o', str(obj)], check=True, timeout=60)
            if target == 'thumbv7em-none':
                b.arm_addends(obj)

            def execute(label, source, mode, expected, required, soft=False, link=False):
                (project/'main.dyn').write_text(source)
                env = dict(os.environ)
                env.pop('DYN_NO_SSA', None)
                if mode == 'tree':
                    env['DYN_NO_SSA'] = '1'
                image = work/f'{label}-{mode}.elf'
                command = [DYN, 'build', str(project), '--release', '--target',
                           target + ('-soft' if soft else ''), '--no-cache', '--opt-remarks',
                           '--output', str(image)]
                if link:
                    command += ['--link', str(obj)]
                build = subprocess.run(command, env=env, capture_output=True, text=True, timeout=120)
                log = build.stdout + build.stderr
                assert build.returncode == 0, (target, label, mode, log)
                check_remarks(log, mode, required)
                if link and target == 'riscv32-none' and mode == 'ssa':
                    # QEMU RV32 may emulate misaligned stores; inspect the actual
                    # forwarding function rather than relying on guest success.
                    dump = subprocess.run([*OBJDUMP, '-d', str(image)], check=True,
                                          capture_output=True, text=True, timeout=60).stdout
                    match = re.search(r'<zeroforward>:\n(.*?)(?=\n[0-9a-f]+ <|\Z)', dump, re.S)
                    assert match, dump
                    stores = re.findall(r'\b(s[bhw])\s+[^\n]+', match[1])
                    byte_stores = stores.count('sb')
                    # Stack/frame stores are allowed. Payload writes must stay
                    # bytewise, whether unrolled or a bounded zero-fill loop.
                    # The independent C oracle below checks exactly eight bytes
                    # and the surrounding canaries; QEMU may emulate wide stores.
                    wide = [line for line in match[1].splitlines()
                            if re.search(r'\b(sh|sw)\s', line) and not re.search(r'\((sp|s0)\)', line)]
                    assert byte_stores > 0 and not wide, match[0]
                    match = re.search(r'<zerochain>:\n(.*?)(?=\n[0-9a-f]+ <|\Z)', dump, re.S)
                    assert match, dump
                    # The aligned intermediate may use wide stack stores, but
                    # the final copy to an unknown/odd address must stay bytewise.
                    # Destination validation follows intermediate initialization.
                    assert '<dyn_check_failed>' in match[1], match[0]
                    final_copy = match[1].rsplit('<dyn_check_failed>', 1)[1]
                    wide = [line for line in final_copy.splitlines()
                            if re.search(r'\b(sh|sw)\s', line) and not re.search(r'\((sp|s0)\)', line)]
                    assert re.search(r'\bsb\s', final_copy) and not wide, match[0]
                actual = calls.run_guest([*qemu, *board, '-nographic', '-kernel', str(image)])
                assert actual == expected, (target, label, mode, expected, actual)

            for mode in ('ssa', 'tree'):
                execute('success', SOURCE, mode, (0, b'LOCALS OK\n', b''), POSITIVE, link=True)
                completed += 1
            alignment_check = 'RV32 byte-store opcodes' if target == 'riscv32-none' else 'Thumb UNALIGN_TRP enabled'
            print(f'PASS {target} success: 13 named SSA; SSA/tree match nine C oracle groups; {alignment_check}', flush=True)
            functions = SOURCE.split('extern fn oracle()')[0] + ORDERED
            for label, expression, function, guard, trace in GUARDS:
                source = functions + 'fn main() { _=' + expression + ' }\n'
                expected = (101, (trace + f'runtime check failed ({guard}) in {function}\n').encode(), b'')
                for mode in ('ssa', 'tree'):
                    execute(label, source, mode, expected, [function])
                    completed += 1
                print(f'PASS {target} {label}: named SSA/tree exact panic and evaluation trace', flush=True)
            soft = SOURCE.split('extern fn oracle()')[0]
            soft = soft.replace('extern fn verifydescs(p:*Descs) u32', 'fn verifydescs(p:*Descs) u32 { return 0 }')
            soft = soft.replace('extern fn verifybox(p:*Box) u64', 'fn verifybox(p:*Box) u64 { return 0 }')
            soft += r'''
fn main() { if arrays(3,100)!=207 || descs(2)!=456 || boxed(123)!=267 { #panic("soft") }
_=io.write_all(io.stdout(),"SOFT OK\n") }
'''
            for mode in ('ssa', 'tree'):
                execute('soft', soft, mode, (0, b'SOFT OK\n', b''),
                        ['arrays', 'descs', 'boxed'], soft=True)
                completed += 1
            print(f'PASS {target}-soft: named SSA/tree lowering and output', flush=True)
    if completed:
        print(f'PASS aggregates: {completed}/40 guests; 15 missing-remark negative controls', flush=True)
    else:
        print('SKIP aggregates: no QEMU targets executed', flush=True)


if __name__ == '__main__':
    main()
