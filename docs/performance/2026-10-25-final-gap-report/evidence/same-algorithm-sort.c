#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
static void swap(uint32_t*a,size_t i,size_t j){uint32_t t=a[i];a[i]=a[j];a[j]=t;}
static void sift(uint32_t*a,size_t root,size_t n){while(root<n/2){size_t child=root*2+1;if(child+1<n&&a[child]<a[child+1])++child;if(!(a[root]<a[child]))return;swap(a,root,child);root=child;}}
static void insertion(uint32_t*a,size_t n){for(size_t i=1;i<n;i++){uint32_t value=a[i];size_t j=i;while(j>0&&value<a[j-1]){a[j]=a[j-1];--j;}a[j]=value;}}
static void heap(uint32_t*a,size_t n){size_t p=n/2;while(p>0){--p;sift(a,p,n);}size_t end=n;while(end>1){--end;swap(a,0,end);sift(a,0,end);}}
static void intro(uint32_t*a,size_t n,size_t depth){while(n>=16){if(depth==0){heap(a,n);return;}--depth;size_t last=n-1,middle=n/2;if(a[middle]<a[0])swap(a,0,middle);if(a[last]<a[middle])swap(a,middle,last);if(a[middle]<a[0])swap(a,0,middle);uint32_t pivot=a[middle];size_t lower=0,cursor=0,upper=n;while(cursor<upper){if(a[cursor]<pivot){swap(a,lower,cursor);++lower;++cursor;}else if(pivot<a[cursor]){--upper;swap(a,upper,cursor);}else ++cursor;}if(lower<n-upper){intro(a,lower,depth);a+=upper;n-=upper;}else{intro(a+upper,n-upper,depth);n=lower;}}insertion(a,n);}
void dyn_sort(uint32_t*a,size_t n){bool ascending=true,descending=true;for(size_t i=1;i<n;i++){if(a[i]<a[i-1])ascending=false;if(a[i-1]<a[i])descending=false;if(!ascending&&!descending)break;}if(ascending)return;if(descending){size_t l=0,r=n;while(l<r){--r;if(l>=r)break;swap(a,l,r);++l;}return;}size_t left=n,depth=0;while(left>1){depth+=2;left/=2;}intro(a,n,depth);}
