#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
/* In-place heapsort avoids libc qsort implementations that allocate. */
static void swap_bytes(char *a, char *b, size_t n) {
    while (n--) { char t=*a; *a++=*b; *b++=t; }
}
static void sift(char *p,size_t root,size_t n,size_t size,int (*cmp)(const void*,const void*)) {
    while (root<n/2) {
        size_t child=root*2+1;
        if (child+1<n && cmp(p+child*size,p+(child+1)*size)<0) child++;
        if (cmp(p+root*size,p+child*size)>=0) break;
        swap_bytes(p+root*size,p+child*size,size); root=child;
    }
}
static void sort(void *p,size_t n,size_t size,int (*cmp)(const void*,const void*)) {
    for (size_t i=n/2;i>0;i--) sift(p,i-1,n,size,cmp);
    for (size_t i=n;i>1;i--) { swap_bytes(p,(char*)p+(i-1)*size,size);sift(p,0,i-1,size,cmp); }
}
#define STBRP_SORT sort
#define STB_RECT_PACK_IMPLEMENTATION
#include <stb_rect_pack.h>
typedef struct { int32_t width,height,x,y,packed; } DynRect;
size_t dyn_stb_pack_size(int width,size_t count) {
    if (width<1 || width>32768 || count>1048576) return 0;
    return (size_t)width*sizeof(stbrp_node)+count*sizeof(stbrp_rect);
}
int dyn_stb_pack(int width,int height,DynRect *rects,size_t count,void *scratch,size_t size) {
    size_t needed=dyn_stb_pack_size(width,count);
    if (!needed || height<1 || height>32768 || !scratch || size<needed || (count && !rects)) return -1;
    for (size_t i=0;i<count;i++) if (rects[i].width<1 || rects[i].height<1 || rects[i].width>32768 || rects[i].height>32768) return -1;
    stbrp_node *nodes=scratch;stbrp_rect *items=(stbrp_rect*)(nodes+width);stbrp_context context;
    for (size_t i=0;i<count;i++) items[i]=(stbrp_rect){.id=(int)i,.w=rects[i].width,.h=rects[i].height};
    stbrp_init_target(&context,width,height,nodes,width);
    int result=stbrp_pack_rects(&context,items,(int)count);
    for (size_t i=0;i<count;i++) { rects[i].packed=items[i].was_packed;rects[i].x=items[i].was_packed?items[i].x:0;rects[i].y=items[i].was_packed?items[i].y:0; }
    return result;
}
typedef void *(*Allocate)(void *context,size_t size);
typedef struct { void *context; Allocate allocate; } Scratch;
static void *scratch_alloc(size_t size,void *context) {
    Scratch *s=context;return s && s->allocate?s->allocate(s->context,size):NULL;
}
#define STBIR_MALLOC(size,user) scratch_alloc(size,user)
#define STBIR_FREE(ptr,user) ((void)(ptr),(void)(user))
#define STB_IMAGE_RESIZE_STATIC
#define STB_IMAGE_RESIZE_IMPLEMENTATION
#include <stb_image_resize2.h>
static bool dimensions(int w,int h,int ow,int oh,int channels) {
    return w>0 && h>0 && ow>0 && oh>0 && w<=32768 && h<=32768 && ow<=32768 && oh<=32768 && channels>=1 && channels<=4 && (uint64_t)w*h*channels<=INT32_MAX && (uint64_t)ow*oh*channels<=INT32_MAX;
}
static void resize_config(STBIR_RESIZE *r,const void *in,int w,int h,void *out,int ow,int oh,int channels,bool srgb,Scratch *scratch) {
    stbir_pixel_layout layouts[]={STBIR_1CHANNEL,STBIR_2CHANNEL,STBIR_RGB,STBIR_RGBA};
    stbir_resize_init(r,in,w,h,0,out,ow,oh,0,layouts[channels-1],srgb?STBIR_TYPE_UINT8_SRGB:STBIR_TYPE_UINT8);
    stbir_set_user_data(r,scratch);
}
bool dyn_stb_resize(const void *in,size_t in_size,int w,int h,void *out,size_t out_size,int ow,int oh,int channels,bool srgb,void *context,Allocate allocate) {
    if (!dimensions(w,h,ow,oh,channels) || !in || !out || !allocate || in_size<(size_t)w*h*channels || out_size<(size_t)ow*oh*channels) return false;
    size_t a=(size_t)w*h*channels,b=(size_t)ow*oh*channels;
    uintptr_t ip=(uintptr_t)in,op=(uintptr_t)out;
    if (ip<=op ? op-ip<a : ip-op<b) return false;
    Scratch scratch={context,allocate};STBIR_RESIZE r;
    resize_config(&r,in,w,h,out,ow,oh,channels,srgb,&scratch);
    return stbir_resize_extended(&r)!=0;
}
