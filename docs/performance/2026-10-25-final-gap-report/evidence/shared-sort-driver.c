#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
extern void dyn_sort(uint32_t*,size_t);
int main(int argc,char**argv){if(argc!=5)return 2;size_t n=strtoull(argv[1],0,10),rounds=strtoull(argv[2],0,10);uint32_t seed=strtoul(argv[3],0,10);unsigned pattern=strtoul(argv[4],0,10);uint32_t*a=malloc(n*4);if(!a)return 3;uint64_t sum=0;for(size_t r=0;r<rounds;r++){uint32_t x=seed+(uint32_t)r;for(size_t i=0;i<n;i++){x=x*1664525u+1013904223u;a[i]=pattern==0?x:pattern==1?(uint32_t)i:pattern==2?(uint32_t)(n-i):pattern==3?7:(x>>24)&15;}dyn_sort(a,n);for(size_t i=0;i<n;i++){if(i&&a[i]<a[i-1])return 4;sum+=(uint64_t)a[i]*(i+1);}}free(a);printf("%llu\n",(unsigned long long)sum);return 0;}
