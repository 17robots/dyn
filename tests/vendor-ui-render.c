/* Native renderer oracle: real software pixels, SDL event ABI, restored state. */
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
