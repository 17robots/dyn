
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
