from pathlib import Path
import subprocess,os,struct,json,time,statistics,hashlib
W=Path(__file__).resolve().parent;R=W.parents[1]
orig=(W/'typed-bin').read_bytes()
symbols={x.split()[-1]:int(x.split()[0],16) for x in subprocess.check_output(['nm','-n',str(W/'typed-bin')],text=True).splitlines() if len(x.split())==3}
def patch(name,address,code):
 b=bytearray(orig); ph=struct.unpack_from('<Q',b,32)[0];size,count=struct.unpack_from('<HH',b,54)
 for i in range(count):
  typ,flags,off,addr,_,filesz,_,_=struct.unpack_from('<IIQQQQQQ',b,ph+i*size)
  if typ==1 and addr<=address and address+len(code)<=addr+filesz:
   pos=off+address-addr;b[pos:pos+len(code)]=code;break
 else:raise AssertionError(address)
 p=W/name;p.write_bytes(b);p.chmod(0o755)
patch('constant-tid-bin',symbols['thread_id'],b'\xb8\x01\0\0\0\xc3')
patch('direct-slot-bin',symbols['unwind_slot'],b'\x48\xb8'+struct.pack('<Q',symbols['unwind_slots'])+b'\xc3')
C=r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct Frame { uint64_t words[16]; };
extern int dyn_unwind_set(struct Frame *) __attribute__((returns_twice));
extern void dyn_unwind_link(struct Frame *);
extern void dyn_unwind_unlink(struct Frame *);
static __attribute__((noinline)) uint64_t *push(unsigned char *base,size_t *offset,size_t cap) {
 if(*offset>cap || cap-*offset<64) abort();
 uint64_t *p=(uint64_t *)(base+*offset);*offset+=64;memset(p,0,64);return p;
}
int main(int argc,char **argv) {
 if(argc!=5)return 2;
 size_t n=strtoull(argv[2],0,10),rounds=strtoull(argv[3],0,10);uint32_t seed=strtoul(argv[4],0,10);
 unsigned char *arena=malloc(n*64);uint64_t **blocks=malloc(n*sizeof(*blocks));if(!arena||!blocks)return 3;
 uint64_t sum=0;struct Frame frame;
 for(size_t r=0;r<rounds;r++) {uint32_t x=seed+(uint32_t)r;size_t offset=0;
  for(size_t i=0;i<n;i++) {
   if(argv[1][0]=='g'){if(dyn_unwind_set(&frame))abort();dyn_unwind_link(&frame);}
   uint64_t *p=push(arena,&offset,n*64);
   if(argv[1][0]=='g')dyn_unwind_unlink(&frame);
   blocks[i]=p;x=x*1664525u+1013904223u;p[0]=x;x=x*1664525u+1013904223u;p[7]=x;
  }
  for(size_t i=0;i<n;i++)sum+=blocks[i][0]+blocks[i][7];
 }
 free(blocks);free(arena);printf("%llu\n",(unsigned long long)sum);return 0;
}
'''
(W/'matched.c').write_text(C)
cmd=['cc','-O3','-std=c11',str(W/'matched.c'),str(R/'build/dynrt_support.o'),str(R/'build/dynrt_shared.o'),'-o',str(W/'matched-c')]
p=subprocess.run(cmd,capture_output=True,text=True);assert p.returncode==0,p.stderr
cases={'dyn':('typed-bin','allocate'),'dyn-constant-tid-diagnostic':('constant-tid-bin','allocate'),'dyn-direct-slot-diagnostic':('direct-slot-bin','allocate'),'dyn-no-cleanup-diagnostic':('no-defer-bin','allocate'),'c-arena':('matched-c','plain'),'c-arena-same-cleanup-runtime':('matched-c','guarded')}
n=8192;rounds=128;seed=912345
expected=json.loads((W/'results.json').read_text())['expected'];results={k:[] for k in cases};order=[]
for i in range(17):
 names=list(cases);names=names[i%len(names):]+names[:i%len(names)]
 if i%2:names.reverse()
 for name in names:
  binary,mode=cases[name];t=time.perf_counter_ns();p=subprocess.run([str(W/binary),mode,str(n),str(rounds),str(seed)],capture_output=True,text=True,timeout=30);elapsed=(time.perf_counter_ns()-t)/1e6
  assert p.returncode==0 and p.stdout==expected and not p.stderr,(name,p)
  if i>=2:results[name].append(elapsed)
 order.append(names)
print({k:statistics.median(v) for k,v in results.items()},flush=True)
(W/'isolation.json').write_text(json.dumps({'n':n,'rounds':rounds,'expected':expected,'warmups':2,'samples':15,'milliseconds':results,'order':order,'c_build':cmd,'binaries':{b:hashlib.sha256((W/b).read_bytes()).hexdigest() for b,m in cases.values()},'limits':['constant-tid and direct-slot are unsafe single-thread diagnostic binary patches, never product changes','no-cleanup loses panic cleanup; never proposed for production','C arena uses simpler metadata than std mem; same size/lifetime/zero initialization','C protected path uses actual unchanged Dyn set/link/unlink runtime']},indent=2))
