#define MINIAUDIO_IMPLEMENTATION
#include <miniaudio.h>
#include <stdbool.h>
#include <string.h>
typedef struct { ma_decoder value; bool live; } DynDecoder;
typedef struct { ma_engine value; bool live; bool device; } DynEngine;
size_t dyn_ma_decoder_size(void) { return sizeof(DynDecoder); }
size_t dyn_ma_decoder_align(void) { return _Alignof(DynDecoder); }
int dyn_ma_decoder_init(void *state,const void *bytes,size_t count) {
    DynDecoder *d=state; memset(d,0,sizeof(*d));
    ma_decoder_config config=ma_decoder_config_init(ma_format_f32,2,48000);
    int code=ma_decoder_init_memory(bytes,count,&config,&d->value); d->live=code==MA_SUCCESS; return code;
}
int dyn_ma_decoder_read(void *state,float *samples,uint64_t frames,uint64_t *read) {
    DynDecoder *d=state; *read=0;
    if (!d || !d->live) return MA_INVALID_ARGS;
    ma_uint64 count=0;int code=ma_decoder_read_pcm_frames(&d->value,samples,frames,&count);*read=count;return code;
}
void dyn_ma_decoder_close(void *state) {
    DynDecoder *d=state; if (d && d->live) { ma_decoder_uninit(&d->value); d->live=false; }
}
size_t dyn_ma_engine_size(void) { return sizeof(DynEngine); }
size_t dyn_ma_engine_align(void) { return _Alignof(DynEngine); }
int dyn_ma_engine_init(void *state,bool device) {
    DynEngine *e=state; memset(e,0,sizeof(*e));
    ma_engine_config config=ma_engine_config_init();
    config.channels=2; config.sampleRate=48000; config.noDevice=!device;
    int code=ma_engine_init(&config,&e->value); e->live=code==MA_SUCCESS; e->device=device; return code;
}
int dyn_ma_play(void *state,const char *path) {
    DynEngine *e=state; if (!e || !e->live || !path) return MA_INVALID_ARGS;
    return ma_engine_play_sound(&e->value,path,NULL);
}
int dyn_ma_mix(void *state,float *samples,uint64_t frames,uint64_t *read) {
    DynEngine *e=state; *read=0;
    if (!e || !e->live || e->device) return MA_INVALID_ARGS;
    ma_uint64 count=0;int code=ma_engine_read_pcm_frames(&e->value,samples,frames,&count);*read=count;return code;
}
void dyn_ma_engine_close(void *state) {
    DynEngine *e=state; if (e && e->live) { ma_engine_uninit(&e->value); e->live=false; }
}
/* Explicit sound handles make completion and stop independent of engine life. */
typedef struct { ma_sound value; bool live; } DynSound;
size_t dyn_ma_sound_size(void) { return sizeof(DynSound); }
size_t dyn_ma_sound_align(void) { return _Alignof(DynSound); }
int dyn_ma_sound_init(void *state,void *engine,const char *path) {
    DynSound *s=state;DynEngine *e=engine;memset(s,0,sizeof(*s));
    if (!e || !e->live || !path) return MA_INVALID_ARGS;
    int code=ma_sound_init_from_file(&e->value,path,MA_SOUND_FLAG_DECODE,NULL,NULL,&s->value);
    s->live=code==MA_SUCCESS;return code;
}
int dyn_ma_sound_start(void *state) { DynSound *s=state;return s && s->live?ma_sound_start(&s->value):MA_INVALID_ARGS; }
int dyn_ma_sound_stop(void *state) { DynSound *s=state;return s && s->live?ma_sound_stop(&s->value):MA_INVALID_ARGS; }
bool dyn_ma_sound_playing(void *state) { DynSound *s=state;return s && s->live && ma_sound_is_playing(&s->value); }
bool dyn_ma_sound_ended(void *state) { DynSound *s=state;return s && s->live && ma_sound_at_end(&s->value); }
int dyn_ma_sound_rewind(void *state) { DynSound *s=state;return s && s->live?ma_sound_seek_to_pcm_frame(&s->value,0):MA_INVALID_ARGS; }
bool dyn_ma_sound_volume(void *state,float volume) {
    DynSound *s=state;if (!s || !s->live || !isfinite(volume) || volume<0 || volume>1) return false;
    ma_sound_set_volume(&s->value,volume);return true;
}
void dyn_ma_sound_close(void *state) { DynSound *s=state;if (s && s->live) { ma_sound_uninit(&s->value);s->live=false; } }
