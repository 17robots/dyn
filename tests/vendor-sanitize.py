#!/usr/bin/env python3
"""Exercise pinned asset/UI adapters and provider alignment fixes under ASan/UBSan."""
import json
import os
import platform
from pathlib import Path
import shlex
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
SOURCES = BUILD / 'extra-vendor-sources'
if platform.system() != 'Linux':
    raise RuntimeError('Provider sanitizer qualification requires native Linux')
required = ['stb/stb_rect_pack.h', 'stb-build/stb_image_resize2.h',
            'microui-build/microui.h', 'microui-build/microui.c']
for name in required:
    if not (SOURCES / name).is_file():
        raise SystemExit('Missing staged provider source; run VENDOR_PACKAGES="stb microui" just vendor-libs')
env = dict(os.environ, SDL_VIDEODRIVER='dummy',
           ASAN_OPTIONS='detect_leaks=1:halt_on_error=1',
           UBSAN_OPTIONS='halt_on_error=1:print_stacktrace=1')
prefix = BUILD / 'vendor-deps/install'
for key, suffix in [('PKG_CONFIG_PATH', 'lib/pkgconfig'), ('LD_LIBRARY_PATH', 'lib')]:
    env[key] = str(prefix / suffix) + (os.pathsep + env[key] if env.get(key) else '')
cc = shlex.split(env.get('CC', 'cc'))
flags = ['-std=c11', '-O1', '-g', '-fsanitize=address,undefined', '-fno-sanitize-recover=all']
sdl = shlex.split(subprocess.check_output(['pkg-config', '--cflags', '--libs', 'sdl3'], env=env, text=True))
STB_ORACLE = r'''#include <assert.h>
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
'''

UI_ORACLE = r'''/* Native renderer oracle: real software pixels, SDL event ABI, restored state. */
#include <SDL3/SDL.h>
#include <assert.h>
#include <math.h>
#include <stddef.h>
#include <stdio.h>
extern size_t dyn_mu_size(void);
extern void dyn_mu_init(void*);
extern bool dyn_mu_begin(void*);
extern bool dyn_mu_end(void*);
extern bool dyn_mu_window(void*,const char*,int,int,int,int);
extern bool dyn_mu_window_end(void*);
extern int dyn_mu_button(void*,const char*);
extern bool dyn_mu_sdl_event(void*,SDL_Renderer*,const SDL_Event*);
extern bool dyn_mu_sdl_render(void*,SDL_Renderer*);
int main(void) {
    assert(SDL_Init(SDL_INIT_VIDEO));
    SDL_Surface *surface=SDL_CreateSurface(320,240,SDL_PIXELFORMAT_RGBA32);assert(surface);
    SDL_Renderer *renderer=SDL_CreateSoftwareRenderer(surface);assert(renderer);
    max_align_t state[(dyn_mu_size()+sizeof(max_align_t)-1)/sizeof(max_align_t)];
    dyn_mu_init(state);assert(!dyn_mu_sdl_render(state,renderer));
    SDL_Rect clip={1,2,3,4};
    SDL_Event event={0};event.type=SDL_EVENT_MOUSE_MOTION;event.motion.x=60;event.motion.y=55;
    bool clicked=false;
    for (int frame=0;frame<4;frame++) {
        event.type=SDL_EVENT_MOUSE_MOTION;event.motion.x=60;event.motion.y=55;
        assert(dyn_mu_sdl_event(state,renderer,&event));
        if (frame==2 || frame==3) {
            event.type=frame==2?SDL_EVENT_MOUSE_BUTTON_DOWN:SDL_EVENT_MOUSE_BUTTON_UP;
            event.button.button=SDL_BUTTON_LEFT;event.button.x=60;event.button.y=55;
            assert(dyn_mu_sdl_event(state,renderer,&event));
        }
        assert(dyn_mu_begin(state));assert(!dyn_mu_sdl_render(state,renderer));
        assert(dyn_mu_window(state,"Panel",10,10,250,200));
        if (dyn_mu_button(state,"Click")==1) clicked=true;
        assert(dyn_mu_window_end(state));assert(dyn_mu_end(state));
        assert(SDL_SetRenderClipRect(renderer,NULL));
        assert(SDL_SetRenderDrawColor(renderer,0,0,0,255));assert(SDL_RenderClear(renderer));
        assert(SDL_SetRenderClipRect(renderer,&clip));
        assert(SDL_SetRenderDrawBlendMode(renderer,SDL_BLENDMODE_NONE));
        assert(SDL_SetRenderDrawColorFloat(renderer,0.125f,0.25f,0.375f,0.5f));
        assert(dyn_mu_sdl_render(state,renderer));assert(SDL_RenderPresent(renderer));
        Uint8 r,g,b,a;SDL_Rect actual;SDL_BlendMode mode;
        assert(SDL_RenderClipEnabled(renderer));assert(SDL_GetRenderClipRect(renderer,&actual));
        assert(actual.x==1 && actual.y==2 && actual.w==3 && actual.h==4);
        assert(SDL_GetRenderDrawBlendMode(renderer,&mode) && mode==SDL_BLENDMODE_NONE);
        float rf,gf,bf,af;
        assert(SDL_GetRenderDrawColorFloat(renderer,&rf,&gf,&bf,&af) && rf==0.125f && gf==0.25f && bf==0.375f && af==0.5f);
        assert(SDL_ReadSurfacePixel(surface,20,100,&r,&g,&b,&a) && (r || g || b));
        assert(SDL_ReadSurfacePixel(surface,300,230,&r,&g,&b,&a) && r==0 && g==0 && b==0);
    }
    assert(clicked);
    event.type=SDL_EVENT_MOUSE_MOTION;event.motion.x=INFINITY;
    assert(!dyn_mu_sdl_event(state,renderer,&event));
    SDL_DestroyRenderer(renderer);SDL_DestroySurface(surface);SDL_Quit();
    puts("PASS SDL UI pixels, input, invalid state and renderer restoration");
}
'''

report = {'status': 'running', 'cases': []}
output = BUILD / 'vendor-sanitize-results.json'
try:
    with tempfile.TemporaryDirectory(prefix='dyn-vendor-sanitize-') as directory:
        work = Path(directory)
        (work/'stb.c').write_text(STB_ORACLE)
        (work/'ui.c').write_text(UI_ORACLE)
        cases = [
            ('stb', [work/'stb.c', ROOT/'vendor/stb/bridge.c'],
             [SOURCES/'stb-build', SOURCES/'stb'], ['-lm']),
            ('ui', [work/'ui.c', ROOT/'vendor/microui/bridge.c',
                    SOURCES/'microui-build/microui.c', ROOT/'vendor/sdl3/microui/bridge.c'],
             [SOURCES/'microui-build'], sdl + ['-lm']),
        ]
        for name, files, includes, links in cases:
            binary = Path(directory) / name
            subprocess.run([*cc, *flags, *['-I'+str(p) for p in includes],
                            *map(str, files), *links, '-o', str(binary)],
                           env=env, check=True, timeout=120)
            subprocess.run([str(binary)], env=env, check=True, timeout=30)
            report['cases'].append(name)
    report['status'] = 'passed'
except BaseException as error:
    report.update(status='failed', error=str(error))
    raise
finally:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2)+'\n')
print('PASS asset/UI native address, undefined-behavior and leak checks')
