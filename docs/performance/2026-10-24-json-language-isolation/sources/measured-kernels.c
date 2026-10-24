#include <stdint.h>
#include <stddef.h>
#include <yyjson.h>
__attribute__((noinline)) uint64_t scan(const uint8_t*p,size_t n,size_t rounds){uint64_t count=0;for(size_t r=0;r<rounds;r++)for(size_t i=0;i<n;i++){uint8_t b=p[i];if(b=='"'||b=='\\'||b<32)count++;}return count;}
__attribute__((noinline)) uint64_t integers(const uint8_t*p,size_t n,size_t rounds){uint64_t sum=0;for(size_t r=0;r<rounds;r++){uint64_t value=0;for(size_t i=0;i<n;i++){uint8_t b=p[i];if(b>='0'&&b<='9'){uint64_t digit=b-'0';if(value>UINT64_C(1844674407370955161)||(value==UINT64_C(1844674407370955161)&&digit>5))return 0;value=value*10+digit;}else{sum+=value;value=0;}}sum+=value;}return sum;}
__attribute__((noinline)) uint64_t records(const uint64_t*p,size_t n,size_t rounds){uint64_t sum=0;for(size_t r=0;r<rounds;r++)for(size_t i=0;i<n/16;i++)if(p[i*2]==3)sum+=p[i*2+1];return sum;}
uint64_t parse_lines(const uint8_t*p,size_t n,size_t rounds){uint64_t sum=0;for(size_t r=0;r<rounds;r++){size_t start=0;for(size_t i=0;i<n;i++)if(p[i]==10){if(i==start){start=i+1;continue;}yyjson_doc*d=yyjson_read((const char*)p+start,i-start,0);if(!d)return 0;sum+=yyjson_get_len(yyjson_doc_get_root(d));yyjson_doc_free(d);start=i+1;}if(start<n){yyjson_doc*d=yyjson_read((const char*)p+start,n-start,0);if(!d)return 0;sum+=yyjson_get_len(yyjson_doc_get_root(d));yyjson_doc_free(d);}}return sum;}
