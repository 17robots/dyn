#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <dlfcn.h>
#include <time.h>
#include <string.h>
typedef uint64_t (*kernel)(const void*,size_t,size_t);
int main(int argc,char**argv){if(argc!=5)return 2;FILE*f=fopen(argv[3],"rb");if(!f)return 3;fseek(f,0,SEEK_END);long len=ftell(f);rewind(f);void*p=malloc((size_t)len);if(!p||fread(p,1,(size_t)len,f)!=(size_t)len)return 4;fclose(f);void*h=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);if(!h){fprintf(stderr,"%s\n",dlerror());return 5;}int one=strcmp(argv[2],"parse_driver")==0;kernel fn=(kernel)dlsym(h,one?"parse_one":argv[2]);if(!fn)return 6;struct timespec a,b;clock_gettime(CLOCK_MONOTONIC,&a);uint64_t result=0;size_t rounds=strtoull(argv[4],0,10);if(one){uint64_t(*init)(void)=dlsym(h,"initialize");void(*destroy)(void)=dlsym(h,"destroy");if(!init||!destroy||!init())return 7;for(size_t r=0;r<rounds;r++){const unsigned char*cur=p,*end=cur+len;while(cur<end){const unsigned char*e=memchr(cur,10,(size_t)(end-cur));if(!e)e=end;if(e>cur)result+=fn(cur,(size_t)(e-cur),0);cur=e==end?end:e+1;}}destroy();}else result=fn(p,(size_t)len,rounds);clock_gettime(CLOCK_MONOTONIC,&b);printf("%llu %.9f\n",(unsigned long long)result,(b.tv_sec-a.tv_sec)+(b.tv_nsec-a.tv_nsec)*1e-9);return 0;}
