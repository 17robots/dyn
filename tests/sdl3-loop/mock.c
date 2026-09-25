#include <SDL3/SDL.h>
#include <stdio.h>
#include <stdlib.h>
static int token, frames, active, polls, renderers, events;
#define HANDLE(T) ((T *)&token)
bool SDL_Init(SDL_InitFlags f) { return true; }
SDL_Window *SDL_CreateWindow(const char *t,int w,int h,SDL_WindowFlags f) { return HANDLE(SDL_Window); }
void SDL_DestroyWindow(SDL_Window *w) {}
SDL_Renderer *SDL_CreateRenderer(SDL_Window *w,const char *n) { renderers++; return HANDLE(SDL_Renderer); }
void SDL_DestroyRenderer(SDL_Renderer *r) {}
bool SDL_SetRenderDrawColor(SDL_Renderer *r, Uint8 a, Uint8 b, Uint8 c, Uint8 d) { return true; }
bool SDL_RenderClear(SDL_Renderer *r) { return true; }
bool SDL_RenderPresent(SDL_Renderer *r) { frames++; return true; }
SDL_GPUDevice *SDL_CreateGPUDevice(SDL_GPUShaderFormat f,bool d,const char *n) { return HANDLE(SDL_GPUDevice); }
void SDL_DestroyGPUDevice(SDL_GPUDevice *d) {}
bool SDL_ClaimWindowForGPUDevice(SDL_GPUDevice *d,SDL_Window *w) { return true; }
void SDL_ReleaseWindowFromGPUDevice(SDL_GPUDevice *d,SDL_Window *w) {}
SDL_GPUCommandBuffer *SDL_AcquireGPUCommandBuffer(SDL_GPUDevice *d) { if(active) abort(); active=1; return HANDLE(SDL_GPUCommandBuffer); }
bool SDL_WaitAndAcquireGPUSwapchainTexture(SDL_GPUCommandBuffer *c,SDL_Window *w,SDL_GPUTexture **t,Uint32 *x,Uint32 *y) {
 if(!active) { fputs("reused submitted command buffer\n",stderr); return false; }
 *t=(getenv("DYN_TEST_MINIMIZED") && *getenv("DYN_TEST_MINIMIZED") && frames==1)?NULL:HANDLE(SDL_GPUTexture); *x=640; *y=360; return true;
}
SDL_GPURenderPass *SDL_BeginGPURenderPass(SDL_GPUCommandBuffer *c,const SDL_GPUColorTargetInfo *t,Uint32 n,const SDL_GPUDepthStencilTargetInfo *d) { return HANDLE(SDL_GPURenderPass); }
void SDL_EndGPURenderPass(SDL_GPURenderPass *p) {}
bool SDL_SubmitGPUCommandBuffer(SDL_GPUCommandBuffer *c) { if(!active) abort(); active=0; frames++; return true; }
bool SDL_WaitEvent(SDL_Event *e) { e->type=events++>=2?SDL_EVENT_QUIT:(events==1?SDL_EVENT_WINDOW_EXPOSED:SDL_EVENT_WINDOW_RESIZED); return true; }
bool SDL_PollEvent(SDL_Event *e) { if(frames>=3 && !polls++) { e->type=SDL_EVENT_QUIT; return true; } return false; }
void SDL_Quit(void) { if(frames!=3 || active || renderers != (getenv("DYN_TEST_RENDERER") ? 1 : 0)) { fprintf(stderr,"FAIL frames=%d active=%d renderers=%d\n",frames,active,renderers); exit(90); } puts("PASS three frames then quit"); fflush(stdout); }
