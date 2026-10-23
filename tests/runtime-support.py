#!/usr/bin/env python3
"""Compare the independent support runtime's exact floating remainders with libm."""
import ctypes
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
    # libc_nonshared's atexit wrapper needs CRT DSO storage even without crtbegin.
    (module/'main.dyn').write_text('#link("c")\nextern fn register "register_cleanup"() i32\nfn main() { if register() != 0 { #panic("atexit") } }\n')
    (work/'atexit.c').write_text('#include <stdlib.h>\n#include <stdio.h>\nextern void *__dso_handle; static void done(void) { puts("atexit cleanup"); } int register_cleanup(void) { if (__dso_handle != 0) return 1; return atexit(done); }\n')
    subprocess.run([*shlex.split(os.environ.get('CC','cc')), '-c', str(work/'atexit.c'),
                    '-o',str(work/'atexit.o')],check=True)
    for flags in ([],['--release']):
        subprocess.run([str(compiler),'build',str(module),'--backend','native',
                        '--link',str(work/'atexit.o'),'--no-cache',
                        '--output',str(work/'atexit'),*flags],check=True)
        result=subprocess.run([str(work/'atexit')],capture_output=True,text=True,timeout=10)
        assert result.returncode == 0 and result.stdout == 'atexit cleanup\n', (result.returncode,result.stdout,result.stderr)
    (work/'identity.c').write_text('extern void *__dso_handle; int dso_identity(void) { return __dso_handle == &__dso_handle; }\n')
    subprocess.run([*shlex.split(os.environ.get('CC','cc')), '-fPIC','-c',str(work/'identity.c'),'-o',str(work/'identity.o')],check=True)
    (module/'main.dyn').write_text('extern fn check "dso_identity"() i32\npub fn identity() i32 { return check() }\n')
    subprocess.run([str(compiler),'build',str(module),'--backend','native','--shared','--no-cache',
                    '--link',str(work/'identity.o'),'--output',str(work/'identity.so')],check=True)
    library = ctypes.CDLL(str(work/'identity.so'))
    assert library.identity() == 1
    # An inherited interposer may reference host-only functions that a child
    # does not provide. Unused PLT entries stay lazy, but used entries bind.
    (module/'main.dyn').write_text('extern fn missing "fixture_missing"() i32\nextern fn present "fixture_present"() i32\npub fn call_missing() i32 { return missing() }\npub fn call_present() i32 { return present() }\n')
    subprocess.run([str(compiler),'build',str(module),'--backend','native','--shared','--no-cache',
                    '--output',str(work/'preload.so')],check=True)
    (work/'preload.c').write_text('#include <dlfcn.h>\n#include <string.h>\nint fixture_present(void) { return 42; } int main(void) { void *p=dlsym(RTLD_DEFAULT,"call_present"); int (*f)(void); memcpy(&f,&p,sizeof(f)); return !f || f()!=42; }\n')
    subprocess.run([*shlex.split(os.environ.get('CC','cc')),str(work/'preload.c'),'-rdynamic','-ldl','-o',str(work/'preload-host')],check=True)
    env = dict(os.environ, LD_PRELOAD=str(work/'preload.so'))
    env.pop('LD_BIND_NOW', None)
    subprocess.run([str(work/'preload-host')],env=env,check=True,timeout=10)
    result=subprocess.run([str(work/'preload-host')],env=dict(env,LD_BIND_NOW='1'),capture_output=True,text=True,timeout=10)
    assert result.returncode != 0 and 'fixture_missing' in result.stderr, result.stderr
    # PIC archives may use local-dynamic TLS; the loader must initialize
    # both .tdata and aligned .tbss independently for every pthread.
    (work/'tls.c').write_text('#include <pthread.h>\nstatic _Thread_local int initialized = 7; static _Thread_local unsigned char zeroed[64] __attribute__((aligned(64))); static void *worker(void *p) { (void)p; if(initialized!=7 || zeroed[63]) return (void*)1; initialized=19; zeroed[63]=31; return 0; } int exercise_tls(void) { pthread_t t; void *result=0; if(initialized!=7 || zeroed[63] || pthread_create(&t,0,worker,0) || pthread_join(t,&result)) return 1; return result!=0 || initialized!=7 || zeroed[63]!=0; }\n')
    (module/'main.dyn').write_text('#link("c")\nextern fn exercise "exercise_tls"() i32\nfn main() { if exercise() != 0 { #panic("TLS isolation") } }\n')
    for model in ('local-dynamic', 'local-exec'):
        subprocess.run([*shlex.split(os.environ.get('CC','cc')), '-fPIC', '-O1','-ftls-model='+model,
                        '-c',str(work/'tls.c'),'-o',str(work/'tls.o')],check=True)
        subprocess.run([str(compiler),'build',str(module),'--backend','native','--no-cache',
                        '--link',str(work/'tls.o'),'--output',str(work/'tls')],check=True)
        subprocess.run([str(work/'tls')],check=True,timeout=10)
    # Freestanding executables have no loader to establish the thread pointer;
    # shared TLS also needs relocation models this linker does not implement.
    (work/'tls-boundary.c').write_text('_Thread_local int boundary = 7; int read_boundary(void) { return boundary; }\n')
    subprocess.run([*shlex.split(os.environ.get('CC','cc')), '-fPIC', '-ftls-model=local-exec',
                    '-c',str(work/'tls-boundary.c'),'-o',str(work/'tls-boundary.o')],check=True)
    (module/'main.dyn').write_text('extern fn read "read_boundary"() i32\nfn main() { _ = read() }\npub fn boundary_value() i32 { return read() }\n')
    for flags in ([], ['--shared']):
        result=subprocess.run([str(compiler),'build',str(module),'--backend','native','--no-cache',
                               '--link',str(work/'tls-boundary.o'),'--output',str(work/'tls-unsupported'),*flags],
                              capture_output=True,text=True,timeout=30)
        assert result.returncode != 0 and 'needs TLS outside the supported x86-64' in result.stderr, (flags,result.returncode,result.stderr)
    # Large sparse heap records must not inherit the stack aggregate bound.
    (module/'main.dyn').write_text('use "std/mem"\nstruct Sparse { first: u8, pad: [2147483648]u8, last: u8 }\nfn main() { arena := mem.arena_create(#sizeof(Sparse) * 2) defer mem.arena_release(&arena) p := #cast(*Sparse, mem.arena_push_uninit(&arena, #sizeof(Sparse) * 2, #alignof(Sparse))) p.first = 17 p.last = 29 view := p[..2] if #cast(usize, &view[1]) - #cast(usize, p) != #sizeof(Sparse) { #panic("large stride") } if p.first != 17 || p.last != 29 { #panic("large offset") } if #cast(usize, &p.last) - #cast(usize, p) != 2147483649 { #panic("offset sign") } }\n')
    for flags in ([],['--release']):
        subprocess.run([str(compiler),'build',str(module),'--backend','native',
                        '--no-cache','--output',str(work/'sparse'),*flags],check=True)
        subprocess.run([str(work/'sparse')],check=True,timeout=10)
    # ELF RUNPATH must locate a relocated library and local scripts hide exports.
    (work/'private').mkdir()
    (work/'library.c').write_text('extern int private_value(void); int answer(void) { return private_value(); }\n')
    subprocess.run([*shlex.split(os.environ.get('CC','cc')), '-shared','-fPIC',str(work/'library.c'),
                    '-Wl,-soname,libfixture.so','-o',str(work/'private/libfixture.so')],check=True)
    (work/'value.c').write_text('int private_value(void) { return 42; }\n')
    subprocess.run([*shlex.split(os.environ.get('CC','cc')), '-c',str(work/'value.c'),'-o',str(work/'value.o')],check=True)
    (module/'main.dyn').write_text('extern fn answer "answer"() i32\nextern fn private_value "private_value"() i32\nfn main() { if answer() != private_value() { #panic("runpath") } }\n')
    subprocess.run([str(compiler),'build',str(module),'--backend','native','--no-cache',
                    '--link',str(work/'value.o'),'--link',str(work/'private/libfixture.so'),'--link','-rpath=$ORIGIN/private',
                    '--output',str(work/'runpath')],check=True)
    subprocess.run([str(work/'runpath')],check=True,timeout=10,env={k:v for k,v in os.environ.items() if k!='LD_LIBRARY_PATH'})
    (work/'local.map').write_text('{ local: private_value; };\n')
    subprocess.run([str(compiler),'build',str(module),'--backend','native','--no-cache',
                    '--link',str(work/'value.o'),'--link',str(work/'private/libfixture.so'),'--link','-rpath=$ORIGIN/private',
                    '--link','--version-script='+str(work/'local.map'),
                    '--output',str(work/'hidden')],check=True)
    result=subprocess.run([str(work/'hidden')],capture_output=True,text=True,timeout=10)
    assert result.returncode != 0 and 'private_value' in result.stderr, result.stderr
    (work/'input.so').write_text('GROUP('+str(work/'value.o')+' '+str(work/'private/libfixture.so')+')\nVERSION { { local: private_value; }; }\n')
    subprocess.run([str(compiler),'build',str(module),'--backend','native','--no-cache',
                    '--link',str(work/'input.so'),'--link','-rpath=$ORIGIN/private',
                    '--output',str(work/'embedded')],check=True)
    result=subprocess.run([str(work/'embedded')],capture_output=True,text=True,timeout=10)
    assert result.returncode != 0 and 'private_value' in result.stderr, result.stderr
    (work/'local.map').write_text('VERSION_1 { global: *; };\n')
    result=subprocess.run([str(compiler),'build',str(module),'--backend','native','--no-cache',
                    '--link',str(work/'value.o'),'--link',str(work/'private/libfixture.so'),'--link','--version-script='+str(work/'local.map'),
                    '--output',str(work/'invalid')],capture_output=True,text=True)
    assert result.returncode != 0 and 'unsupported version script' in result.stderr, result.stderr
print('PASS independent runtime exact fmod/fmodf (30,000 pairs) null-message panic cleanup, libc atexit, sparse heap layouts, RUNPATH, symbol visibility lazy interposers and pthread TLS')
