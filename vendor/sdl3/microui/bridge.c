#include <SDL3/SDL.h>
#include <stdbool.h>
#include <math.h>
extern bool dyn_mu_ready(void*);
extern void dyn_mu_mouse(void*,int,int,int);
extern void dyn_mu_scroll(void*,int,int);
extern void *dyn_mu_next(void*);
extern int dyn_mu_kind(void*);
extern const char *dyn_mu_text(void*);
extern void dyn_mu_rect(void*,int*,int*,int*,int*);
extern unsigned dyn_mu_color(void*);
extern int dyn_mu_icon(void*);
/* Coordinates are converted by SDL to the renderer's logical space. */
bool dyn_mu_sdl_event(void *context,SDL_Renderer *renderer,const SDL_Event *source) {
    if (!context || !renderer || !source) return false;
    SDL_Event e=*source;
    if (!SDL_ConvertEventToRenderCoordinates(renderer,&e)) return false;
    float x=0,y=0;int action=0;
    switch (e.type) {
    case SDL_EVENT_MOUSE_MOTION:x=e.motion.x;y=e.motion.y;break;
    case SDL_EVENT_MOUSE_BUTTON_DOWN:
    case SDL_EVENT_MOUSE_BUTTON_UP:
        if (e.button.button!=SDL_BUTTON_LEFT) return false;
        x=e.button.x;y=e.button.y;action=e.type==SDL_EVENT_MOUSE_BUTTON_DOWN?1:2;break;
    case SDL_EVENT_MOUSE_WHEEL:
        x=e.wheel.x;y=e.wheel.y;
        if (!isfinite(x) || !isfinite(y) || fabsf(x)>1000 || fabsf(y)>1000) return false;
        if (e.wheel.direction==SDL_MOUSEWHEEL_FLIPPED) { x=-x;y=-y; }
        dyn_mu_scroll(context,(int)(-x*30),(int)(-y*30));return true;
    case SDL_EVENT_WINDOW_FOCUS_LOST:dyn_mu_mouse(context,0,0,2);return true;
    default:return false;
    }
    if (!isfinite(x) || !isfinite(y) || fabsf(x)>1000000 || fabsf(y)>1000000) return false;
    dyn_mu_mouse(context,(int)x,(int)y,action);return true;
}
bool dyn_mu_sdl_render(void *context,SDL_Renderer *renderer) {
    if (!context || !renderer || !dyn_mu_ready(context)) return false;
    SDL_Rect saved;SDL_BlendMode blend;float r,g,b,a;
    bool clipped=SDL_RenderClipEnabled(renderer);
    if (!SDL_GetRenderClipRect(renderer,&saved) || !SDL_GetRenderDrawBlendMode(renderer,&blend) || !SDL_GetRenderDrawColorFloat(renderer,&r,&g,&b,&a)) return false;
    bool ok=SDL_SetRenderDrawBlendMode(renderer,SDL_BLENDMODE_BLEND) && SDL_SetRenderClipRect(renderer,NULL);
    void *command;
    while (ok && (command=dyn_mu_next(context))) {
        int x,y,w,h;dyn_mu_rect(command,&x,&y,&w,&h);int kind=dyn_mu_kind(command);
        if (kind==2) { SDL_Rect clip={x,y,w,h};ok=SDL_SetRenderClipRect(renderer,&clip);continue; }
        unsigned color=dyn_mu_color(command);
        ok=SDL_SetRenderDrawColor(renderer,color>>24,(color>>16)&255,(color>>8)&255,color&255);
        if (!ok) break;
        SDL_FRect rect={(float)x,(float)y,(float)w,(float)h};
        if (kind==3) ok=SDL_RenderFillRect(renderer,&rect);
        else if (kind==4) ok=SDL_RenderDebugText(renderer,(float)x,(float)y+4,dyn_mu_text(command));
        else if (kind==5) {
            float cx=x+w*0.5f,cy=y+h*0.5f;int icon=dyn_mu_icon(command);
            if (icon==1) ok=SDL_RenderLine(renderer,cx-4,cy-4,cx+4,cy+4) && SDL_RenderLine(renderer,cx-4,cy+4,cx+4,cy-4);
            else if (icon==2) ok=SDL_RenderLine(renderer,cx-4,cy,cx-1,cy+3) && SDL_RenderLine(renderer,cx-1,cy+3,cx+5,cy-4);
            else if (icon==3) ok=SDL_RenderLine(renderer,cx-2,cy-4,cx+2,cy) && SDL_RenderLine(renderer,cx+2,cy,cx-2,cy+4);
            else if (icon==4) ok=SDL_RenderLine(renderer,cx-4,cy-2,cx,cy+2) && SDL_RenderLine(renderer,cx,cy+2,cx+4,cy-2);
        }
    }
    bool restored=SDL_SetRenderClipRect(renderer,clipped?&saved:NULL);
    restored=SDL_SetRenderDrawBlendMode(renderer,blend) && restored;
    restored=SDL_SetRenderDrawColorFloat(renderer,r,g,b,a) && restored;
    return ok && restored;
}
