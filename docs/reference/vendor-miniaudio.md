# vendor/miniaudio

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/audio-playback-example/main.dyn](../../projects/audio-playback-example/main.dyn), [projects/miniaudio-example/main.dyn](../../projects/miniaudio-example/main.dyn), [tests/vendor-extra.py](../../tests/vendor-extra.py)

## Declarations and source contracts

## Source: compiler/vendor/miniaudio/miniaudio.dyn

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L7)

miniaudio 0.11.23. Context bytes belong to caller arena. Provider owns its
internal allocations/workers. Close before resetting arena; never move state.
Input bytes must remain alive and unchanged until decoder_close.

```dyn
pub struct Context { value: rawptr, code: i32, ok: bool }
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L8)

```dyn
pub struct Read { samples: usize, code: i32, ended: bool, ok: bool }
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L9)

```dyn
pub fn decoder_create(arena: *mem.Arena, bytes: []const u8) Context
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L19)

```dyn
pub fn decoder_read(decoder: rawptr, output: []f32) Read
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L24)

```dyn
pub extern fn decoder_close "dyn_ma_decoder_close"(decoder: rawptr)
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L27)

device=false gives deterministic offline mixing. device=true opens the default
playback device; its availability/latency require hardware qualification.

```dyn
pub fn engine_create(arena: *mem.Arena, device: bool) Context
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L36)

```dyn
pub fn play_file(engine: rawptr, path: []const u8, buffer: []u8) bool
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L42)

Offline engine only. Outputs interleaved stereo f32 at 48 kHz.

```dyn
pub fn mix(engine: rawptr, output: []f32) Read
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L47)

```dyn
pub extern fn engine_close "dyn_ma_engine_close"(engine: rawptr)
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L60)

Sound state lives in arena; provider synchronously decodes the file. Close
sounds BEFORE their engine, then rewind/release storage. Starts paused.

```dyn
pub fn sound_create(arena: *mem.Arena, engine: rawptr, path: []const u8, buffer: []u8) Context
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L71)

Native result: 0 success, negative error. stop preserves position; rewind
explicitly seeks to the start. Query ended to distinguish EOF from a stop.

```dyn
pub extern fn sound_start "dyn_ma_sound_start"(sound: rawptr) i32
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L72)

```dyn
pub extern fn sound_stop "dyn_ma_sound_stop"(sound: rawptr) i32
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L73)

```dyn
pub extern fn sound_rewind "dyn_ma_sound_rewind"(sound: rawptr) i32
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L74)

```dyn
pub extern fn sound_playing "dyn_ma_sound_playing"(sound: rawptr) bool
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L75)

```dyn
pub extern fn sound_ended "dyn_ma_sound_ended"(sound: rawptr) bool
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L76)

```dyn
pub extern fn sound_volume "dyn_ma_sound_volume"(sound: rawptr, volume: f32) bool
```

[Source](../../compiler/vendor/miniaudio/miniaudio.dyn#L77)

```dyn
pub extern fn sound_close "dyn_ma_sound_close"(sound: rawptr)
```
