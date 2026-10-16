#!/usr/bin/env python3
"""Compare the independent support runtime's exact floating remainders with libm."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
SOURCE = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include <dlfcn.h>
extern double fmod(double,double);
extern float fmodf(float,float);
static uint64_t state=0x1729374658123456ULL;
static uint64_t random_bits(void) { state^=state<<13;state^=state>>7;state^=state<<17;return state; }
int main(void) {
 void *library=dlopen("libm.so.6",RTLD_NOW);
 if(!library) { fputs(dlerror(),stderr);return 2; }
 double (*reference)(double,double); float (*referencef)(float,float);
 void *p=dlsym(library,"fmod");memcpy(&reference,&p,sizeof(p));
 p=dlsym(library,"fmodf");memcpy(&referencef,&p,sizeof(p));
 if(!reference||!referencef)return 2;
 for(unsigned i=0;i<30000;i++) {
   uint64_t a=random_bits(),b=random_bits();double x,y;memcpy(&x,&a,8);memcpy(&y,&b,8);
   double actual=fmod(x,y),expected=reference(x,y);
   if(!(isnan(actual)&&isnan(expected))&&memcmp(&actual,&expected,8))return 3;
   uint32_t c=(uint32_t)a,d=(uint32_t)b;float xf,yf;memcpy(&xf,&c,4);memcpy(&yf,&d,4);
   float actualf=fmodf(xf,yf),expectedf=referencef(xf,yf);
   if(!(isnan(actualf)&&isnan(expectedf))&&memcmp(&actualf,&expectedf,4))return 4;
 }
 dlclose(library);return 0;
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-runtime-support-') as directory:
    work=Path(directory)
    (work/'test.c').write_text(SOURCE)
    subprocess.run([*shlex.split(os.environ.get('CC','cc')), '-fno-builtin', '-O2',
                    str(work/'test.c'), str(BUILD/'dynrt_support.o'), str(BUILD/'dynrt_shared.o'),
                    '-ldl','-o',str(work/'test')],check=True)
    subprocess.run([str(work/'test')],check=True,timeout=30)
    # A C callback may initiate a panic without a message; cleanup still runs.
    module=work/'module'
    module.mkdir()
    (module/'main.dyn').write_text('use "std/io"\nextern fn fail "null_panic"()\nfn main() { defer { _ = io.println(io.stdout(), "cleanup") } fail() }\n')
    (work/'callback.c').write_text('#include <stdint.h>\nextern void dyn_panic(const void *,uint64_t); void null_panic(void) { dyn_panic(0,0); }\n')
    subprocess.run([*shlex.split(os.environ.get('CC','cc')), '-c', str(work/'callback.c'),
                    '-o',str(work/'callback.o')],check=True)
    compiler=Path(os.environ.get('DYN',BUILD/'dyn')).resolve()
    for flags in ([],['--release']):
        subprocess.run([str(compiler),'build',str(module),'--backend','native',
                        '--link',str(work/'callback.o'),'--output',str(work/'panic'),*flags],check=True)
        result=subprocess.run([str(work/'panic')],capture_output=True,text=True,timeout=10)
        assert result.returncode != 0 and result.stdout == 'cleanup\n', (result.returncode,result.stdout,result.stderr)
print('PASS independent runtime exact fmod/fmodf (30,000 pairs) and null-message panic cleanup')
