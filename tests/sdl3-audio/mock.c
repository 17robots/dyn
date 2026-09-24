#include <SDL3/SDL.h>
#include <stdio.h>
#include <stdlib.h>
static int token, supplied, flushed, resumed, polls, drained;
bool SDL_Init(SDL_InitFlags flags) { return true; }
void SDL_Quit(void) {}
SDL_AudioStream *SDL_OpenAudioDeviceStream(SDL_AudioDeviceID device, const SDL_AudioSpec *spec, SDL_AudioStreamCallback cb, void *context) {
    if (spec->format != SDL_AUDIO_U8 || spec->channels != 1 || spec->freq != 8000) abort();
    return (SDL_AudioStream *)&token;
}
bool SDL_PutAudioStreamData(SDL_AudioStream *s, const void *data, int len) {
    const unsigned char *bytes = data;
    if (len != 2000 || resumed) abort();
    for (int i=0; i<len; i++) if (bytes[i] != (i%20<10 ? 140 : 116)) abort();
    supplied = 1;
    return true;
}
bool SDL_FlushAudioStream(SDL_AudioStream *s) { if (!supplied) abort(); flushed=1; return true; }
bool SDL_ResumeAudioStreamDevice(SDL_AudioStream *s) { if (!flushed) abort(); resumed=1; return true; }
int SDL_GetAudioStreamAvailable(SDL_AudioStream *s) {
    if (!resumed) abort();
    if (getenv("DYN_TEST_AUDIO_ERROR")) return -1;
    if (getenv("DYN_TEST_AUDIO_STALL")) return 2000;
    if (++polls < 4) return 2000;
    drained = 1;
    return 0;
}
void SDL_DestroyAudioStream(SDL_AudioStream *s) {
    if (getenv("DYN_TEST_AUDIO_ERROR") || getenv("DYN_TEST_AUDIO_STALL")) return;
    if (!drained || polls < 4) { fputs("audio destroyed before drain\n", stderr); exit(91); }
    puts("PASS audio lifetime"); fflush(stdout);
}
