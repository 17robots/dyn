
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint32_t next(uint32_t *x){return *x=*x*1664525u+1013904223u;}
static int compare(const void*a,const void*b){uint32_t x=*(const uint32_t*)a,y=*(const uint32_t*)b;return(x>y)-(x<y);}
int main(int argc,char**argv){if(argc!=5)return 2;char *mode=argv[1];size_t n=strtoull(argv[2],0,10),rounds=strtoull(argv[3],0,10);uint32_t seed=strtoul(argv[4],0,10);uint64_t sum=0;
if(!strcmp(mode,"sort")){uint32_t*a=malloc(n*4);if(!a)return 3;for(size_t r=0;r<rounds;r++){uint32_t x=seed+(uint32_t)r;for(size_t i=0;i<n;i++)a[i]=next(&x);qsort(a,n,4,compare);for(size_t i=0;i<n;i++)sum+=(uint64_t)a[i]*(i+1);}free(a);}
else if(!strcmp(mode,"map")){size_t cap=1;while(cap<n*2)cap*=2;uint32_t*k=calloc(cap,4),*v=calloc(cap,4),*input=malloc(n*4);if(!k||!v||!input)return 3;for(size_t r=0;r<rounds;r++){memset(k,0,cap*4);memset(v,0,cap*4);uint32_t x=seed+(uint32_t)r;for(size_t i=0;i<n;i++){uint32_t key=1+(next(&x)>>8)%(n*8);input[i]=key;size_t p=(uint32_t)(key*2654435761u)&(cap-1);while(k[p]&&k[p]!=key)p=(p+1)&(cap-1);k[p]=key;v[p]++;}for(size_t p=0;p<cap;p++)sum+=(uint64_t)k[p]*v[p];for(size_t i=0;i<n;i++){uint32_t key=input[i];size_t p=(uint32_t)(key*2654435761u)&(cap-1);while(k[p]!=key)p=(p+1)&(cap-1);sum+=(uint64_t)key*v[p];}}free(k);free(v);free(input);}
else if(!strcmp(mode,"utf8")){unsigned char*a=malloc(n*4);if(!a)return 3;size_t used=0;uint32_t x=seed;for(size_t i=0;i<n;i++){uint32_t c=next(&x)%0x10f800;if(c>=0xd800)c+=0x800;if(c<128)a[used++]=c;else if(c<2048){a[used++]=192|(c>>6);a[used++]=128|(c&63);}else if(c<65536){a[used++]=224|(c>>12);a[used++]=128|((c>>6)&63);a[used++]=128|(c&63);}else{a[used++]=240|(c>>18);a[used++]=128|((c>>12)&63);a[used++]=128|((c>>6)&63);a[used++]=128|(c&63);}}for(size_t r=0;r<rounds;r++){size_t i=0;while(i<used){uint32_t c=a[i++];unsigned more=0;if(c>=240){c&=7;more=3;}else if(c>=224){c&=15;more=2;}else if(c>=192){c&=31;more=1;}while(more--){c=(c<<6)|(a[i++]&63);}sum+=c;}}free(a);}
else if(!strcmp(mode,"allocate")){uint64_t**a=malloc(n*sizeof(*a));if(!a)return 3;for(size_t r=0;r<rounds;r++){uint32_t x=seed+(uint32_t)r;for(size_t i=0;i<n;i++){a[i]=calloc(8,8);if(!a[i])return 3;a[i][0]=next(&x);a[i][7]=next(&x);}for(size_t i=0;i<n;i++){sum+=a[i][0]+a[i][7];free(a[i]);}}free(a);}else return 2;printf("%llu\n",(unsigned long long)sum);return 0;}
