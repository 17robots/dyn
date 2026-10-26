#!/usr/bin/env python3
"""Linux x64 frame-local unwind ownership: exact identity calls, slot reuse and chunk growth."""
import os
from pathlib import Path
import platform
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = Path(os.environ.get('DYN', ROOT / 'build/dyn')).resolve()
SOURCE = r'''
#include <assert.h>
#include <pthread.h>
#include <setjmp.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdatomic.h>
#include <stdio.h>
#include <sys/mman.h>
struct frame { void *previous; uint64_t saved[15]; };
extern void dyn_unwind_link(struct frame *);
extern void dyn_unwind_unlink(struct frame *);
static _Thread_local uint64_t identity = 1;
static _Thread_local unsigned calls;
static _Thread_local unsigned loads;
static atomic_uint chunks;
long dyn_syscall6(long n,long a,long b,long c,long d,long e,long f) {
 if(n==9) { /* Slot chunks come from anonymous pages on first use. */
  void *p=mmap((void *)a,(size_t)b,(int)c,(int)d,(int)e,f);
  assert(p!=MAP_FAILED);atomic_fetch_add(&chunks,1);return (long)p;
 }
 assert(n==186);calls++;return (long)identity;
}
uint64_t dyn_atomic_load_u64(uint64_t *p) { loads++;return atomic_load((_Atomic uint64_t *)p); }
void dyn_atomic_store_u64(uint64_t *p,uint64_t v) { atomic_store((_Atomic uint64_t *)p,v); }
_Bool dyn_atomic_compare_exchange_u64(uint64_t *p,uint64_t a,uint64_t b) {
 return atomic_compare_exchange_strong((_Atomic uint64_t *)p,&a,b);
}
void dyn_unwind_jump(void *p) { (void)p;abort(); }
uintptr_t dyn_unwind_tables_start(void) { return 0; }
uintptr_t dyn_unwind_tables_stop(void) { return 0; }
void dyn_panic(const char *p,uint64_t n) { (void)p;(void)n;abort(); }
static void exercise(void) {
 for(unsigned k=0;k<1000;k++) {
  struct frame a,b;memset(&a,0xa5,sizeof a);memset(&b,0x5a,sizeof b);
  unsigned before=calls;dyn_unwind_link(&a);dyn_unwind_link(&b);
  if(b.previous!=&a) { fprintf(stderr,"owner nesting tid=%llu iteration=%u previous=%p wanted=%p\n",(unsigned long long)identity,k,b.previous,(void*)&a);abort(); } assert(!a.previous);
  dyn_unwind_unlink(&a); /* Non-top frames remain linked. */
  dyn_unwind_unlink(&b);dyn_unwind_unlink(&a);dyn_unwind_unlink(&a);
  assert(calls==before+2); /* Unlink performs no identity syscall. */
  for(unsigned i=0;i<15;i++) if(i!=8) {
   assert(a.saved[i]==UINT64_C(0xa5a5a5a5a5a5a5a5));
   assert(b.saved[i]==UINT64_C(0x5a5a5a5a5a5a5a5a));
  }
  assert(a.saved[8]==0 && b.saved[8]==0);
 }
}
static void *worker(void *p) { identity=(uintptr_t)p;exercise();return 0; }
int main(void) {
 /* Nothing is reserved before the first cleanup frame. */
 assert(chunks==0);
 /* Repeated empty-stack calls reuse a validated hint, not a full scan.
    Count atomic reads rather than asserting noisy wall-clock performance.
    Each link also reads the first chunk address. */
 struct frame repeated={0};
 for(unsigned i=0;i<1000;i++) { dyn_unwind_link(&repeated);dyn_unwind_unlink(&repeated); }
 assert(loads<=3100 && calls==1000 && chunks==1);
 /* An active first owner keeps a two-read nested fast path. */
 struct frame outer={0},inner={0};dyn_unwind_link(&outer);
 unsigned nested_reads=loads;
 for(unsigned i=0;i<1000;i++) { dyn_unwind_link(&inner);dyn_unwind_unlink(&inner); }
 assert(loads-nested_reads==2000);dyn_unwind_unlink(&outer);
 /* Releasing a lower slot must not hide an existing higher owner. */
 struct frame lower={0},higher={0},nested={0};
 identity=1;dyn_unwind_link(&lower);
 identity=2;dyn_unwind_link(&higher);
 identity=1;dyn_unwind_unlink(&lower);
 identity=2;dyn_unwind_link(&nested);
 assert(nested.previous==&higher);
 dyn_unwind_unlink(&nested);dyn_unwind_unlink(&higher);
 identity=1;exercise();
 pthread_t threads[16];
 for(uintptr_t i=0;i<16;i++) assert(!pthread_create(&threads[i],0,worker,(void *)(i+100)));
 for(unsigned i=0;i<16;i++) assert(!pthread_join(threads[i],0));
 /* Hash collisions must preserve nesting and independently owned frames. */
 for(uintptr_t i=0;i<16;i++) assert(!pthread_create(&threads[i],0,worker,(void *)(i*64+1)));
 for(unsigned i=0;i<16;i++) assert(!pthread_join(threads[i],0));
 /* Opaque identities above the packed range must not alias a smaller tid. */
 identity=UINT64_C(1)<<60;exercise();
 identity=(UINT64_C(1)<<60)+1;exercise();
 /* More than one chunk of simultaneous owners grows the registry instead of
    panicking, and every owner keeps its own chain. */
 enum { owners=200 };
 struct frame frames[owners],nested_frames[owners];memset(frames,0,sizeof frames);memset(nested_frames,0,sizeof nested_frames);
 for(identity=1;identity<=owners;identity++) dyn_unwind_link(&frames[identity-1]);
 assert(chunks==4);
 for(identity=1;identity<=owners;identity++) { dyn_unwind_link(&nested_frames[identity-1]);assert(nested_frames[identity-1].previous==&frames[identity-1]); }
 for(identity=1;identity<=owners;identity++) { dyn_unwind_unlink(&nested_frames[identity-1]);dyn_unwind_unlink(&frames[identity-1]); }
 /* Released slots are reused; no further chunks are reserved. */
 for(identity=1;identity<=owners;identity++) dyn_unwind_link(&frames[identity-1]);
 for(identity=1;identity<=owners;identity++) dyn_unwind_unlink(&frames[identity-1]);
 assert(chunks==4);
 for(identity=1000;identity<1100;identity++) exercise();
 return 0;
}
'''
if platform.system() != 'Linux' or platform.machine() != 'x86_64':
    print('SKIP unwind owner: requires Linux x64')
else:
    with tempfile.TemporaryDirectory(prefix='dyn-unwind-owner-') as directory:
        work = Path(directory)
        subprocess.run([str(DYN), 'build', str(ROOT / 'runtime/support'),
                        '--backend', 'native', '--release', '--shared', '--emit-object',
                        '--no-link', '--runtime-support', '--target', 'x86_64-linux',
                        '--output', str(work / 'support'), '--quiet'], check=True, timeout=120)
        (work / 'test.c').write_text(SOURCE)
        subprocess.run([*shlex.split(os.environ.get('CC', 'cc')), '-std=c11', '-O2',
                        '-Wall', '-Wextra', '-Werror', '-pthread', str(work / 'test.c'),
                        str(work / 'support.o'), '-o', str(work / 'test')], check=True, timeout=60)
        subprocess.run([str(work / 'test')], check=True, timeout=30)
    print('PASS unwind owner: nesting, identity count, register canaries, colliding threads, full identities, lazy chunks, growth past 64 owners, reuse, bounded hint reads, two-read nested path')
