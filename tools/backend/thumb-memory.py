#!/usr/bin/env python3
"""Execute production Thumb copy/zero emission against a full-buffer oracle.

Run from any directory with Python 3. Requires cc, clang, ld.lld, and qemu-arm.
All generated sources, machine code, and executables live in a temporary directory.
Tests lengths 0..80: 518400 copy cases and 648 zero cases, including overlap,
identical pointers, every byte alignment, and unchanged surrounding canaries.
"""

from pathlib import Path
import re
import shutil
import subprocess as sp
import tempfile


def run(d):
    p = (Path(__file__).resolve().parents[2] / 'src/backend/t32.inc').read_text()
    names=['t16','t32w','t32_dp','t32_mv','t32_modimm','t32_dpi','t32_movw','t32_li','t32_mem','t32_branch_at','t32_skip','t32_land','t32_jump','t32_back','t32_zero_fill','t32_copy']
    parts=[]
    for name in names:
        m = re.search(r'static [^\n]*\b' + name + r'\(', p)
        if m is None:
            raise RuntimeError(f'Cannot find production emitter {name}')
        start = m.start()
        b = p.index('{', m.end())
        depth = 1
        e = b + 1
        while depth:
            depth += (p[e] == '{') - (p[e] == '}')
            e += 1
        parts.append(p[start:e])
    head='''#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>
#include <stdio.h>
typedef struct { struct { unsigned char data[4096]; size_t n; bool failed; } text; } BackendContext;
static void byte(BackendContext*c,unsigned v){c->text.data[c->text.n++]=v;}
static void patch_word(BackendContext*c,size_t a,uint32_t v){memcpy(c->text.data+a,&v,4);}
'''
    head+='\n'.join(re.findall(r'enum \{.*?\};',p[:p.index('static void t32_vmem')],re.S))+'\n'
    head+=re.search(r'static const unsigned short t32_memory_op\[\].*?;',p).group()+'\n'
    head+='#define T32_OP(op,d,n,m) t32_dp(c,op,false,d,n,m,0,0)\n#define T32_CMP(n,m) t32_dp(c,T32_SUB,true,15,n,m,0,0)\n#define R_DI 0\n'
    # Production pop encoding, including DI high-word transfer; wrapper provides 16-byte slot.
    head+='static void t32_pop(BackendContext*c,int r){(void)r;unsigned char b[]={0xfd,0xe8,0x04,0x6a,0x09,0xee,0x10,0xaa};for(unsigned i=0;i<sizeof b;i++)byte(c,b[i]);}\n'
    main='''int main(void){for(unsigned n=0;n<=80;n++)for(unsigned cp=0;cp<2;cp++){BackendContext c={0};if(cp)t32_copy(&c,n);else t32_zero_fill(&c,n);if(c.text.failed)return 1;char path[80];sprintf(path,"%c%u.bin",cp?'c':'z',n);FILE*f=fopen(path,"wb");fwrite(c.text.data,1,c.text.n,f);fclose(f);}return 0;}'''
    (d/'emit.c').write_text(head+'\n'.join(parts)+main)
    sp.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(d/'emit.c'),'-o',str(d/'emit')],check=True);sp.run([str(d/'emit')],cwd=d,check=True)
    asm='.syntax unified\n.thumb\n.fpu vfpv3-d16\n.text\n.global _start\n.thumb_func\n_start:\nbl test\nmov r7,#1\nsvc #0\n'
    for n in range(81):
        for cp in ['z','c']:
            asm+=f'.global {cp}{n}\n.thumb_func\n{cp}{n}:\npush {{r3-r11,lr}}\nvpush {{d8-d15}}\n'
            if cp=='c':asm+='sub sp,sp,#16\nstr r1,[sp]\nmov r2,#0\nstr r2,[sp,#4]\n'
            asm+=f'.incbin "{cp}{n}.bin"\nvpop {{d8-d15}}\npop {{r3-r11,pc}}\n'
    (d/'run.S').write_text(asm)
    src='typedef void (*fn)(unsigned char*,unsigned char*);\n'
    for n in range(81):src+=f'extern void z{n}(unsigned char*,unsigned char*),c{n}(unsigned char*,unsigned char*);\n'
    for cp in ['z','c']:src+=f'fn {cp}[]={{'+','.join(f'{cp}{n}' for n in range(81))+'};\n'
    src+='''unsigned char a[256] __attribute__((aligned(4))),b[256],tmp[256];
int test(void){
for(unsigned n=0;n<=80;n++){
 for(unsigned off=0;off<8;off++){
  for(unsigned i=0;i<256;i++)a[i]=b[i]=(i*37+11)&255;
  z[n](a+off,0);for(unsigned i=0;i<n;i++)b[off+i]=0;
  for(unsigned i=0;i<256;i++)if(a[i]!=b[i])return 1;
 }
 for(unsigned s=0;s<80;s++)for(unsigned dst=0;dst<80;dst++){
  for(unsigned i=0;i<256;i++)a[i]=b[i]=(i*37+11)&255;
  for(unsigned i=0;i<n;i++)tmp[i]=b[s+i];
  for(unsigned i=0;i<n;i++)b[dst+i]=tmp[i];
  c[n](a+s,a+dst);
  for(unsigned i=0;i<256;i++)if(a[i]!=b[i])return 2;
 }
}return 0;}
'''
    (d/'test.c').write_text(src)
    sp.run(['clang','--target=armv7-linux-gnueabihf','-march=armv7-a','-mthumb','-mfpu=vfpv3-d16','-mfloat-abi=hard','-O2','-ffreestanding','-fno-builtin','-nostdlib','-static','-fuse-ld=lld',str(d/'test.c'),str(d/'run.S'),'-o',str(d/'test')],cwd=d,check=True)
    sp.run(['qemu-arm',str(d/'test')],cwd=d,check=True)
    print('PASS: 518400 memmove cases + 648 zero fills; lengths 0..80, all alignments, both overlap directions, identical pointers, full-buffer canaries')



def main():
    missing = [tool for tool in ('cc', 'clang', 'ld.lld', 'qemu-arm')
               if shutil.which(tool) is None]
    if missing:
        print('SKIP: Thumb memory harness requires: ' + ', '.join(missing))
        return
    with tempfile.TemporaryDirectory(prefix='thumb-memory-') as directory:
        run(Path(directory))


if __name__ == '__main__':
    main()
