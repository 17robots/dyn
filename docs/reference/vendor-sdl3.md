# vendor/sdl3

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-sdl3/main.dyn](../../tests/sdk-sdl3/main.dyn)
- [tests/vendor-packages/abi/main.dyn](../../tests/vendor-packages/abi/main.dyn)

Reviewed behavioral fixtures: [projects/sdl3-font-example/main.dyn](../../projects/sdl3-font-example/main.dyn), [projects/sdl3-image-example/main.dyn](../../projects/sdl3-image-example/main.dyn), [tests/vendor-packages.py](../../tests/vendor-packages.py), [tests/vendor-packages/abi/main.dyn](../../tests/vendor-packages/abi/main.dyn)

## Declarations and source contracts

## Source: compiler/vendor/sdl3/gl.dyn

[Source](../../compiler/vendor/sdl3/gl.dyn#L3)

OpenGL context lifecycle. Create a WindowOpenGL window after setting attributes.
Context and loaded procedure addresses are thread/context-affine.

```dyn
pub const WindowOpenGL: u64 = 2
```

[Source](../../compiler/vendor/sdl3/gl.dyn#L4)

```dyn
pub type GlContext = rawptr
```

[Source](../../compiler/vendor/sdl3/gl.dyn#L5)

```dyn
pub fn gl_request_core(major: i32, minor: i32) bool
```

[Source](../../compiler/vendor/sdl3/gl.dyn#L9)

```dyn
pub fn gl_create_owned(window: Window) GlContext
```

[Source](../../compiler/vendor/sdl3/gl.dyn#L10)

```dyn
pub fn gl_destroy_owned(context: GlContext) bool
```

[Source](../../compiler/vendor/sdl3/gl.dyn#L11)

```dyn
pub fn gl_make_current(window: Window, context: GlContext) bool
```

[Source](../../compiler/vendor/sdl3/gl.dyn#L14)

Name must be NUL-terminated; call with current context. Can supply directly to
vendor/opengl.load. This function does not allocate or cache addresses.

```dyn
pub fn gl_proc(name: *const u8) rawptr
```

[Source](../../compiler/vendor/sdl3/gl.dyn#L15)

```dyn
pub fn gl_swap(window: Window) bool
```

[Source](../../compiler/vendor/sdl3/gl.dyn#L16)

```dyn
pub fn gl_swap_interval(interval: i32) bool
```

[Source](../../compiler/vendor/sdl3/gl.dyn#L17)

```dyn
pub fn window_pixel_size(window: Window, width: *i32, height: *i32) bool
```

## Source: compiler/vendor/sdl3/raw_generated.dyn

## Source: compiler/vendor/sdl3/sdl3.dyn

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L7)

Optional SDL3 adapter; importing this package links SDL3. Handles are
SDL-owned allocations with matching destroy_owned operations.

```dyn
pub type Window = rawptr
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L8)

```dyn
pub type Renderer = rawptr
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L9)

```dyn
pub const InitAudio: u32 = 16
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L10)

```dyn
pub const InitVideo: u32 = 32
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L11)

```dyn
pub const WindowResizable: u64 = 32
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L12)

```dyn
pub const WindowHidden: u64 = 8
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L13)

```dyn
pub const EventQuit: u32 = 256
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L14)

```dyn
pub const EventWindowCloseRequested: u32 = 528
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L15)

```dyn
pub const EventWindowDestroyed: u32 = 537
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L16)

```dyn
pub struct WindowResult { value: Window, ok: bool }
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L17)

```dyn
pub struct RendererResult { value: Renderer, ok: bool }
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L20)

SDL_Event has a stable 128-byte ABI. u64 words preserve its required
eight-byte alignment while keeping the large C union out of Dyn's API.

```dyn
pub struct Event { words: [16]u64 }
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L23)

```dyn
pub fn init_video() bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L24)

```dyn
pub fn init_audio() bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L25)

```dyn
pub fn quit()
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L26)

```dyn
pub fn window_create(title: []const u8, title_buffer: []u8, width: i32, height: i32, flags: u64) WindowResult
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L33)

```dyn
pub fn window_destroy_owned(window: Window)
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L34)

```dyn
pub fn renderer_create_default_owned(window: Window) RendererResult
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L39)

```dyn
pub fn renderer_destroy_owned(renderer: Renderer)
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L40)

```dyn
pub fn clear(renderer: Renderer, red: u8, green: u8, blue: u8, alpha: u8) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L43)

```dyn
pub fn present(renderer: Renderer) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L44)

```dyn
pub fn event_type(event: *const Event) u32
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L48)

```dyn
pub fn poll_event(event: *Event) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L51)

```dyn
pub fn wait_event(event: *Event) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L54)

```dyn
pub fn event_requests_close(event: *const Event) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L59)

Borrows SDL thread-local buffer until the next SDL call.

```dyn
pub fn last_error(maximum: usize) c.BytesResult
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L61)

```dyn
pub type AudioStream = rawptr
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L62)

```dyn
pub type AudioDevice = u32
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L63)

```dyn
pub type AudioCallback = *fn(rawptr, AudioStream, i32, i32)
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L64)

```dyn
pub const AudioDeviceDefaultPlayback: AudioDevice = 4294967295
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L65)

```dyn
pub const AudioU8: u32 = 8
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L66)

```dyn
pub const AudioS16: u32 = 32784
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L67)

```dyn
pub const AudioF32: u32 = 33056
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L68)

```dyn
pub struct AudioSpec { format: u32, channels: i32, frequency: i32 }
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L69)

```dyn
pub struct AudioStreamResult { value: AudioStream, ok: bool }
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L73)

SDL owns the stream allocation. nil callbacks select explicitly queued audio.

```dyn
pub fn stream_open_playback_owned(spec: *const AudioSpec) AudioStreamResult
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L78)

```dyn
pub fn stream_open_playback_callback_owned(spec: *const AudioSpec, callback: AudioCallback, context: rawptr) AudioStreamResult
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L84)

SDL copies source before return; source stays caller-owned.

```dyn
pub fn stream_put(stream: AudioStream, source: []const u8) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L89)

```dyn
pub fn stream_resume(stream: AudioStream) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L90)

```dyn
pub fn stream_pause(stream: AudioStream) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L91)

```dyn
pub fn stream_available(stream: AudioStream) i32
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L92)

```dyn
pub fn stream_flush(stream: AudioStream) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L93)

```dyn
pub fn stream_clear(stream: AudioStream) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L94)

```dyn
pub fn stream_format(stream: AudioStream, source: *AudioSpec, destination: *AudioSpec) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L95)

```dyn
pub fn stream_destroy_owned(stream: AudioStream)
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L97)

```dyn
pub type GpuDevice = rawptr
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L98)

```dyn
pub type GpuCommandBuffer = rawptr
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L99)

```dyn
pub type GpuTexture = rawptr
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L100)

```dyn
pub type GpuRenderPass = rawptr
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L101)

```dyn
pub type GpuShader = rawptr
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L102)

```dyn
pub type GpuBuffer = rawptr
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L103)

```dyn
pub const ShaderSpirv: u32 = 2
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L104)

```dyn
pub const ShaderDxbc: u32 = 4
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L105)

```dyn
pub const ShaderDxil: u32 = 8
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L106)

```dyn
pub const ShaderMsl: u32 = 16
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L107)

```dyn
pub const ShaderMetallib: u32 = 32
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L108)

```dyn
pub const ShaderStageVertex: i32 = 0
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L109)

```dyn
pub const ShaderStageFragment: i32 = 1
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L110)

```dyn
pub const BufferVertex: u32 = 1
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L111)

```dyn
pub const BufferIndex: u32 = 2
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L112)

```dyn
pub const TextureSampler: u32 = 1
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L113)

```dyn
pub const TextureColorTarget: u32 = 2
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L114)

```dyn
pub struct GpuDeviceResult { value: GpuDevice, ok: bool }
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L115)

```dyn
pub struct GpuSwapchainResult { texture: GpuTexture, width: u32, height: u32, ok: bool }
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L116)

```dyn
pub struct FColor { red: f32, green: f32, blue: f32, alpha: f32 }
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L117)

```dyn
pub struct GpuColorTargetInfo {
  texture: GpuTexture, mip_level: u32, layer_or_depth_plane: u32, clear_color: FColor,
  load_op: i32, store_op: i32, resolve_texture: GpuTexture, resolve_mip_level: u32,
  resolve_layer: u32, cycle: bool, cycle_resolve_texture: bool, padding1: u8, padding2: u8,
}
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L122)

```dyn
pub struct GpuShaderInfo {
  code_size: usize, code: *const u8, entrypoint: c.string, format: u32, stage: i32,
  samplers: u32, buffer_textures: u32, buffer_buffers: u32, uniform_buffers: u32, properties: u32,
}
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L126)

```dyn
pub struct GpuTextureInfo {
  kind: i32, format: i32, usage: u32, width: u32, height: u32, layers_or_depth: u32,
  levels: u32, samples: i32, properties: u32,
}
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L130)

```dyn
pub struct GpuBufferInfo { usage: u32, size: u32, properties: u32 }
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L133)

```dyn
pub fn gpu_create_default_owned(formats: u32, debug: bool) GpuDeviceResult
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L137)

```dyn
pub fn gpu_destroy_owned(device: GpuDevice)
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L138)

```dyn
pub fn gpu_claim_window(device: GpuDevice, window: Window) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L139)

```dyn
pub fn gpu_release_window(device: GpuDevice, window: Window)
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L140)

```dyn
pub fn gpu_commands(device: GpuDevice) GpuCommandBuffer
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L141)

```dyn
pub fn gpu_wait_swapchain(commands: GpuCommandBuffer, window: Window) GpuSwapchainResult
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L147)

Submission consumes the command buffer regardless of success.

```dyn
pub fn gpu_submit(commands: GpuCommandBuffer) bool
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L148)

```dyn
pub fn gpu_shader_create_owned(device: GpuDevice, info: *const GpuShaderInfo) GpuShader
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L149)

```dyn
pub fn gpu_shader_release_owned(device: GpuDevice, shader: GpuShader)
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L150)

```dyn
pub fn gpu_texture_create_owned(device: GpuDevice, info: *const GpuTextureInfo) GpuTexture
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L151)

```dyn
pub fn gpu_texture_release_owned(device: GpuDevice, texture: GpuTexture)
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L152)

```dyn
pub fn gpu_buffer_create_owned(device: GpuDevice, info: *const GpuBufferInfo) GpuBuffer
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L153)

```dyn
pub fn gpu_buffer_release_owned(device: GpuDevice, buffer: GpuBuffer)
```

[Source](../../compiler/vendor/sdl3/sdl3.dyn#L157)

Clears and presents one swapchain frame, consuming commands on success.
A minimized window may have no texture; submit the empty buffer successfully.

```dyn
pub fn gpu_clear_swapchain(commands: GpuCommandBuffer, window: Window, color: FColor) bool
```

## Source: compiler/vendor/sdl3/surface.dyn

[Source](../../compiler/vendor/sdl3/surface.dyn#L2)

Shared SDL-owned surface/texture lifecycle for image and font providers.

```dyn
pub type Surface = rawptr
```

[Source](../../compiler/vendor/sdl3/surface.dyn#L3)

```dyn
pub type Texture = rawptr
```

[Source](../../compiler/vendor/sdl3/surface.dyn#L4)

```dyn
pub struct SurfaceResult { value: Surface, ok: bool }
```

[Source](../../compiler/vendor/sdl3/surface.dyn#L5)

```dyn
pub struct TextureResult { value: Texture, ok: bool }
```

[Source](../../compiler/vendor/sdl3/surface.dyn#L6)

```dyn
pub struct Color { red: u8, green: u8, blue: u8, alpha: u8 }
```

[Source](../../compiler/vendor/sdl3/surface.dyn#L7)

```dyn
pub fn surface_destroy_owned(surface: Surface)
```

[Source](../../compiler/vendor/sdl3/surface.dyn#L9)

Upload copies surface data; surface may be destroyed after this call.

```dyn
pub fn texture_from_surface_owned(renderer: Renderer, surface: Surface) TextureResult
```

[Source](../../compiler/vendor/sdl3/surface.dyn#L14)

```dyn
pub fn texture_destroy_owned(texture: Texture)
```

[Source](../../compiler/vendor/sdl3/surface.dyn#L16)

Draw entire texture to entire rendering target. Present separately.

```dyn
pub fn texture_draw(renderer: Renderer, texture: Texture) bool
```
