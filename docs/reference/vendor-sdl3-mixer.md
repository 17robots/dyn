# vendor/sdl3/mixer

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/sdl3-mixer-example/main.dyn](../../projects/sdl3-mixer-example/main.dyn), [tests/vendor-extra.py](../../tests/vendor-extra.py)

## Declarations and source contracts

## Source: compiler/vendor/sdl3/mixer/mixer.dyn

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L6)

SDL_mixer 3.2.4. Balance init/quit after destroying mixers and audio.
SDL owns these allocations. Destroy tracks before mixers; destroying a mixer
also destroys its remaining tracks. Track pointers then become invalid.

```dyn
pub type Mixer = rawptr
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L7)

```dyn
pub type Audio = rawptr
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L8)

```dyn
pub type Track = rawptr
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L9)

```dyn
pub struct Result { written: usize, code: i32, ok: bool }
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L10)

```dyn
pub extern fn init "MIX_Init"() bool
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L11)

```dyn
pub extern fn quit "MIX_Quit"()
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L13)

Offline stereo f32 at 48 kHz, no device. Pull audio into caller storage.

```dyn
pub fn create_owned() Mixer
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L19)

Default playback device; availability and output latency are device-dependent.
Use playing/stop with this mixer; generate is only for offline mixers.

```dyn
pub fn create_device_owned() Mixer
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L20)

```dyn
pub fn destroy_owned(mixer: Mixer)
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L23)

Source borrowed only during synchronous predecode; provider owns the audio.
Audio can outlive the originating mixer and must be destroyed separately.

```dyn
pub fn decode_owned(mixer: Mixer, bytes: []const u8) Audio
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L29)

```dyn
pub fn audio_destroy_owned(audio: Audio)
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L30)

```dyn
pub fn track_create(mixer: Mixer) Track
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L31)

```dyn
pub fn track_destroy(track: Track)
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L32)

```dyn
pub fn play(track: Track, audio: Audio) bool
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L33)

```dyn
pub fn stop(track: Track) bool
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L34)

```dyn
pub fn playing(track: Track) bool
```

[Source](../../compiler/vendor/sdl3/mixer/mixer.dyn#L37)

Samples are interleaved stereo f32. Length must be even. written is the
number of meaningful samples; provider fills the remaining output with silence.

```dyn
pub fn generate(mixer: Mixer, samples: []f32) Result
```
