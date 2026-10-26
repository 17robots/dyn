#!/usr/bin/env python3
"""LP64D aggregates split between a7 and the stack retain every argument."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve()
SOURCE = '''struct Pair { x: i64, y: i64 }
extern fn c_spill(a:i64,b:i64,c:i64,d:i64,e:i64,f:i64,g:i64,p:Pair,tail:i64) i64
extern fn c_callback(callback:fn(i64,i64,i64,i64,i64,i64,i64,Pair,i64) i64) i64
fn dyn_spill(a:i64,b:i64,c:i64,d:i64,e:i64,f:i64,g:i64,p:Pair,tail:i64) i64 {
  return a+b+c+d+e+f+g+p.x*10+p.y*100+tail*1000
}
fn main() {
  if c_spill(1,2,3,4,5,6,7,Pair{x:8,y:2},3) != 3308 { #panic("split outgoing aggregate") }
  if c_spill(-1,-2,-3,-4,-5,-6,-7,Pair{x:-8,y:-2},-3) != -3308 { #panic("signed split outgoing aggregate") }
  if c_callback(dyn_spill) != 3308 { #panic("split incoming aggregate") }
}
'''
PROVIDER = '''typedef long long i64;
typedef struct { i64 x,y; } Pair;
i64 c_spill(i64 a,i64 b,i64 c,i64 d,i64 e,i64 f,i64 g,Pair p,i64 tail) {
  return a+b+c+d+e+f+g+p.x*10+p.y*100+tail*1000;
}
i64 c_callback(i64 (*callback)(i64,i64,i64,i64,i64,i64,i64,Pair,i64)) {
  return callback(1,2,3,4,5,6,7,(Pair){8,2},3);
}
'''


def main():
    clang = shlex.split(os.environ.get('CLANG', 'clang'))
    qemu = shutil.which('qemu-riscv64')
    if not clang or not shutil.which(clang[0]) or not qemu:
        print('SKIP RISC-V SSA ABI: needs Clang and qemu-riscv64')
        return
    with tempfile.TemporaryDirectory(prefix='dyn-rv-ssa-abi-') as directory:
        work = Path(directory)
        (work/'main.dyn').write_text(SOURCE)
        (work/'provider.c').write_text(PROVIDER)
        provider = work/'provider.o'
        subprocess.run([*clang, '--target=riscv64-unknown-linux-gnu', '-march=rv64g', '-mno-relax',
                        '-ffreestanding', '-fno-stack-protector', '-O1', '-c', work/'provider.c',
                        '-o', provider], check=True)
        for name, extra in [('ssa', {}), ('tree', {'DYN_NO_SSA': '1'})]:
            output = work/name
            result = subprocess.run([DYN, 'build', work, '--target', 'riscv64-linux', '--release',
                                     '--no-cache', '--quiet', '--opt-remarks', '--link', provider,
                                     '--output', output], env={**os.environ, **extra},
                                    capture_output=True, text=True)
            assert result.returncode == 0, result.stderr
            if name == 'ssa':
                for function in ('dyn_spill', 'main'):
                    assert f'remark: {function}: SSA code generation,' in result.stderr, result.stderr
            subprocess.run([qemu, output], check=True, timeout=30)
    print('PASS RISC-V SSA split aggregate C ABI, incoming/outgoing and tree baseline')

if __name__ == '__main__':
    main()
