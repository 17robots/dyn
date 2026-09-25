#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stddef.h>
#include <string.h>
typedef struct { int32_t width,height,x,y,packed; } Rectangle;
extern size_t dyn_stb_pack_size(int,size_t);
extern int dyn_stb_pack(int,int,Rectangle*,size_t,void*,size_t);
extern bool dyn_stb_resize(const void*,size_t,int,int,void*,size_t,int,int,int,bool,void*,void *(*)(void*,size_t));
typedef struct { unsigned char *data;size_t size,used; } Arena;
static void *allocate(void *context,size_t size) {
    Arena *a=context;size_t offset=(a->used+63)&~(size_t)63;
    if (offset>a->size || size>a->size-offset) return NULL;
    a->used=offset+size;return a->data+offset;
}
static uint32_t seed=1234567;
static unsigned random_value(void) { seed=seed*1664525+1013904223;return seed; }
int main(void) {
    _Alignas(64) unsigned char scratch[1024*1024];
    Rectangle rects[64];
    for (int pass=0;pass<100;pass++) {
        for (int i=0;i<64;i++) rects[i]=(Rectangle){.width=1+(int)(random_value()%16),.height=1+(int)(random_value()%16)};
        assert(dyn_stb_pack_size(64,64)<=sizeof(scratch));
        int result=dyn_stb_pack(64,64,rects,64,scratch,sizeof(scratch));assert(result>=0);
        for (int i=0;i<64;i++) if (rects[i].packed) {
            Rectangle a=rects[i];assert(a.x>=0 && a.y>=0 && a.x+a.width<=64 && a.y+a.height<=64);
            for (int j=i+1;j<64;j++) if (rects[j].packed) {
                Rectangle b=rects[j];assert(a.x+a.width<=b.x || b.x+b.width<=a.x || a.y+a.height<=b.y || b.y+b.height<=a.y);
            }
        }
    }
    unsigned char input[16*16*4],output[32*32*4];memset(input,127,sizeof(input));
    for (int channels=1;channels<=4;channels++) for (int srgb=0;srgb<=1;srgb++) for (int width=1;width<=32;width*=2) {
        Arena arena={scratch,1,0};
        assert(!dyn_stb_resize(input,sizeof(input),16,16,output,sizeof(output),width,width,channels,srgb,&arena,allocate));
        arena=(Arena){scratch,sizeof(scratch),0};
        assert(dyn_stb_resize(input,sizeof(input),16,16,output,sizeof(output),width,width,channels,srgb,&arena,allocate));
        for (int i=0;i<width*width*channels;i++) assert(output[i]>=126 && output[i]<=128);
    }
    Arena invalid={scratch,sizeof(scratch),0};
    assert(!dyn_stb_resize(input,sizeof(input),32768,32768,output,sizeof(output),1,1,4,false,&invalid,allocate));
    assert(invalid.used==0);
    assert(!dyn_stb_pack_size(0,64));
    puts("PASS stb randomized non-overlap, channel/color-space resizes and short scratch");
}
