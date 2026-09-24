# Native provider API notes — 2026-09-23

Research for the initial Dyn SDL_mixer, Box2D, and ENet packages. These are pinned integration contracts, not a claim of complete upstream API coverage. Provider allocations remain provider-owned; Dyn-owned heap storage must use arenas. Avoid allocating wrapper handles merely to hold an upstream value ID.

## Verified source pins

| Provider | Stable tag | Immutable commit |
| --- | --- | --- |
| [SDL_mixer](https://github.com/libsdl-org/SDL_mixer/releases/tag/release-3.2.4) | release-3.2.4 | `72a81869b45e249e8e67102db4e98dd2441f05a1` |
| [Box2D](https://github.com/erincatto/box2d/releases/tag/v3.1.1) | v3.1.1 | `8c661469c9507d3ad6fbd2fea3f1aa71669c2fe3` |
| [ENet](https://github.com/lsalzman/enet/tree/v1.3.18) | v1.3.18 | `2662c0de09e36f2a2030ccc2c528a3e4c9e8138a` |

Tags and their commit hashes were queried from the official repository APIs; headers below were read at those commits.

## SDL_mixer

Put the optional package at `vendor/sdl3/mixer`. SDL3 uses the redesigned uppercase `MIX_*` API. Its CMake requires SDL 3.4.0 or newer. WAV decoding is built in with `SDLMIXER_WAVE=ON`; disable unneeded codec options, tests, and examples for a minimal build without optional codec downloads. Use `BUILD_SHARED_LIBS=ON`, `SDLMIXER_VENDORED=OFF`, `SDLMIXER_TESTS=OFF`, and `SDLMIXER_EXAMPLES=OFF`. The project has individual codec toggles, not one universal disable-all switch. [Pinned build configuration](https://github.com/libsdl-org/SDL_mixer/blob/72a81869b45e249e8e67102db4e98dd2441f05a1/CMakeLists.txt).

Minimal declarations:

```c
bool MIX_Init(void);
void MIX_Quit(void);
MIX_Mixer *MIX_CreateMixer(const SDL_AudioSpec *spec);
MIX_Mixer *MIX_CreateMixerDevice(SDL_AudioDeviceID devid, const SDL_AudioSpec *spec);
MIX_Audio *MIX_LoadAudio(MIX_Mixer *mixer, const char *path, bool predecode);
MIX_Audio *MIX_LoadAudio_IO(MIX_Mixer *mixer, SDL_IOStream *io,
                          bool predecode, bool closeio);
MIX_Track *MIX_CreateTrack(MIX_Mixer *mixer);
bool MIX_SetTrackAudio(MIX_Track *track, MIX_Audio *audio);
bool MIX_PlayTrack(MIX_Track *track, SDL_PropertiesID options);
bool MIX_StopTrack(MIX_Track *track, Sint64 fade_out_frames);
bool MIX_TrackPlaying(MIX_Track *track);
int MIX_Generate(MIX_Mixer *mixer, void *buffer, int buflen);
void MIX_DestroyTrack(MIX_Track *track);
void MIX_DestroyAudio(MIX_Audio *audio);
void MIX_DestroyMixer(MIX_Mixer *mixer);
```

Use options `0` for default playback and fade `0` for immediate stop. Offline mixers require a nonnull format; generation takes **bytes**, aligned to the output sample-frame size. A successful call initializes the entire buffer, adding silence after tracks end, while returning only the real audio byte count. Negative means failure. Device mixers cannot use `MIX_Generate`. IO loading caches audio; `closeio=true` closes the stream on success and failure. Tracks retain audio references. Destroying a mixer destroys its tracks/groups, but not independently owned audio. Match successful init calls with quit calls; never destroy objects after final quit. [Pinned public header](https://github.com/libsdl-org/SDL_mixer/blob/72a81869b45e249e8e67102db4e98dd2441f05a1/include/SDL3_mixer/SDL_mixer.h).

Suggested offline test: load generated nonzero PCM WAV, play, generate into a caller buffer, assert nonzero samples, consume through completion, assert silence afterward, replay, stop, verify stopped state. This verifies mixing, not audible hardware playback.

## Box2D

The library compiles as C17. CMake 3.22+ configures both C and C++ toolchains; disable `BOX2D_SAMPLES`, `BOX2D_UNIT_TESTS`, and `BOX2D_BENCHMARKS` to avoid their extra dependencies and unpinned enkiTS fetch. Keep default AVX2 off for portable x86-64 packages. [Top-level build](https://github.com/erincatto/box2d/blob/8c661469c9507d3ad6fbd2fea3f1aa71669c2fe3/CMakeLists.txt), [library build](https://github.com/erincatto/box2d/blob/8c661469c9507d3ad6fbd2fea3f1aa71669c2fe3/src/CMakeLists.txt).

A C shim can expose world IDs as `uint32_t`, body/shape IDs as `uint64_t`, using upstream inline `b2StoreWorldId`/`b2LoadWorldId`, `b2StoreBodyId`/`b2LoadBodyId`, and `b2StoreShapeId`/`b2LoadShapeId`. Do not reproduce private bit layouts in Dyn or turn IDs into pointers. Zero denotes null; generation-based validity checks are available but cannot promise indefinite stale-handle detection. [Pinned ID helpers](https://github.com/erincatto/box2d/blob/8c661469c9507d3ad6fbd2fea3f1aa71669c2fe3/include/box2d/id.h).

Initialize configuration with `b2DefaultWorldDef`, `b2DefaultBodyDef`, and `b2DefaultShapeDef`; zeroed structs are insufficient. The shim can accept a few scalar parameters and fill these provider structs on the C stack. [Definition requirements](https://github.com/erincatto/box2d/blob/8c661469c9507d3ad6fbd2fea3f1aa71669c2fe3/include/box2d/types.h).

Core operations are `b2CreateWorld`, `b2DestroyWorld`, `b2CreateBody`, `b2DestroyBody`, `b2CreatePolygonShape`, `b2DestroyShape(shape, updateBodyMass)`, `b2World_Step(world, float dt, int substeps)`, and `b2Body_GetPosition`. Use fixed steps, typically 1/60 second with four substeps. Validate IDs before calling operations that assume valid objects. World destruction invalidates contained object handles; body destruction removes its shapes and joints. [Pinned public API](https://github.com/erincatto/box2d/blob/8c661469c9507d3ad6fbd2fea3f1aa71669c2fe3/include/box2d/box2d.h).

Suggested test: static ground plus dynamic box; step until resting and assert position with tolerance; explicitly destroy a body and assert invalidity; then destroy the world. Do not claim cross-platform deterministic simulation based on one local test.

## ENet

Pinned CMake hardcodes a static target; `BUILD_SHARED_LIBS` does not change it. Archives install under `lib/static`. A shared wrapper linking that archive requires position-independent code on applicable systems. Windows needs its socket/timing libraries. [Pinned CMake](https://github.com/lsalzman/enet/blob/2662c0de09e36f2a2030ccc2c528a3e4c9e8138a/CMakeLists.txt).

```c
ENetHost *enet_host_create(const ENetAddress *, size_t peerCount,
                          size_t channelLimit, enet_uint32 incomingBandwidth,
                          enet_uint32 outgoingBandwidth);
ENetPeer *enet_host_connect(ENetHost *, const ENetAddress *, size_t channelCount,
                           enet_uint32 data);
int enet_host_service(ENetHost *, ENetEvent *, enet_uint32 timeout_ms);
void enet_host_flush(ENetHost *);
ENetPacket *enet_packet_create(const void *, size_t, enet_uint32 flags);
int enet_peer_send(ENetPeer *, enet_uint8 channel, ENetPacket *);
void enet_packet_destroy(ENetPacket *);
void enet_peer_disconnect(ENetPeer *, enet_uint32 data);
void enet_host_destroy(ENetHost *);
```

Initialize/deinitialize the library around hosts. Address host values use network byte order and port values host byte order; use `enet_address_set_host_ip` for numeric localhost instead of manually encoding the address. Prefer a shim for event and packet access to avoid copying exposed provider struct layouts. [Pinned header](https://github.com/lsalzman/enet/blob/2662c0de09e36f2a2030ccc2c528a3e4c9e8138a/include/enet/enet.h).

Both endpoints must call `enet_host_service`; zero timeout is nonblocking. Results: positive event, zero timeout, negative error. Normal packet creation copies bytes. A successful send transfers packet ownership; destroy a packet yourself if sending fails. Received packets require explicit destruction after inspection. Borrowed packet slices expire at destruction. Avoid `NO_ALLOCATE` in the initial convenience API because it adds asynchronous caller-buffer lifetime requirements. [Official tutorial](https://github.com/lsalzman/enet/blob/2662c0de09e36f2a2030ccc2c528a3e4c9e8138a/docs/tutorial.dox), [send implementation](https://github.com/lsalzman/enet/blob/2662c0de09e36f2a2030ccc2c528a3e4c9e8138a/peer.c).

Suggested test: loopback server on an ephemeral port and client, service both until connected, send reliable bytes, echo a copy, compare exact lengths/content, release every received packet, then destroy hosts. Bound the loop with a deadline. Reliable UDP delivery is not encryption or peer authentication.
