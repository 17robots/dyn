
#include <stdint.h>
#include <stddef.h>
static long syscall3(long n,long a,long b,long c){long r;__asm__ volatile("syscall":"=a"(r):"a"(n),"D"(a),"S"(b),"d"(c):"rcx","r11","memory");return r;}
static unsigned char data[32768];static size_t length;
size_t configure(void){char input[128];long n=syscall3(0,0,(long)input,sizeof(input));size_t p=0,k=0,rounds=0;while(p<(size_t)n&&input[p]>='0'&&input[p]<='9')k=k*10+(input[p++]-'0');while(p<(size_t)n&&input[p]==' ')p++;while(p<(size_t)n&&input[p]>='0'&&input[p]<='9')rounds=rounds*10+(input[p++]-'0');size_t sizes[]={0,1,7,16,64,4096,64,64};if(k>=8||!rounds)__builtin_trap();data[length++]='"';if(k==6){for(size_t i=0;i<64;i++){const char*s="\\u0061";for(size_t j=0;j<6;j++)data[length++]=s[j];}}else if(k==7){for(size_t i=0;i<32;i++){data[length++]=0xc3;data[length++]=0xa9;}}else for(size_t i=0;i<sizes[k];i++)data[length++]='a';data[length++]='"';return rounds;}
const unsigned char*document(void){return data;}
size_t document_length(void){return length;}
void report(uint64_t value){char b[64];size_t n=0;do{b[n++]=(char)('0'+value%10);value/=10;}while(value);for(size_t i=0;i<n/2;i++){char t=b[i];b[i]=b[n-i-1];b[n-i-1]=t;}b[n++]='\n';syscall3(1,1,(long)b,n);}
