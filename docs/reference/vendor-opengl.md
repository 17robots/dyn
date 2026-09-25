# vendor/opengl

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/opengl-example/main.dyn](../../projects/opengl-example/main.dyn), [tests/vendor-packages.py](../../tests/vendor-packages.py)

## Declarations and source contracts

## Source: compiler/vendor/opengl/opengl.dyn

[Source](../../compiler/vendor/opengl/opengl.dyn#L5)

OpenGL 3.3 core subset. No link dependency: caller supplies context loader.
Table belongs to that context and thread; reload for a different context.
Calls use native GL contracts and errors (get_error); no hidden allocations.

```dyn
pub type Loader = *fn(*const u8) rawptr
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L6)

```dyn
pub const ColorBufferBit: u32 = 16384
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L7)

```dyn
pub const VertexShader: u32 = 35633
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L8)

```dyn
pub const FragmentShader: u32 = 35632
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L9)

```dyn
pub const CompileStatus: u32 = 35713
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L10)

```dyn
pub const LinkStatus: u32 = 35714
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L11)

```dyn
pub const ArrayBuffer: u32 = 34962
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L12)

```dyn
pub const StaticDraw: u32 = 35044
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L13)

```dyn
pub const Float: u32 = 5126
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L14)

```dyn
pub const Triangles: u32 = 4
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L15)

```dyn
pub const Rgba: u32 = 6408
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L16)

```dyn
pub const UnsignedByte: u32 = 5121
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L17)

```dyn
pub struct Api {
  clear_color: *fn(f32, f32, f32, f32),
  clear: *fn(u32),
  viewport: *fn(i32, i32, i32, i32),
  get_error: *fn() u32,
  get_integer: *fn(u32, *i32),
  create_shader: *fn(u32) u32,
  shader_source: *fn(u32, i32, **const u8, *const i32),
  compile_shader: *fn(u32),
  get_shader_iv: *fn(u32, u32, *i32),
  get_shader_log: *fn(u32, i32, *i32, *u8),
  delete_shader: *fn(u32),
  create_program: *fn() u32,
  attach_shader: *fn(u32, u32),
  link_program: *fn(u32),
  get_program_iv: *fn(u32, u32, *i32),
  get_program_log: *fn(u32, i32, *i32, *u8),
  use_program: *fn(u32),
  delete_program: *fn(u32),
  gen_vertex_arrays: *fn(i32, *u32),
  bind_vertex_array: *fn(u32),
  delete_vertex_arrays: *fn(i32, *const u32),
  gen_buffers: *fn(i32, *u32),
  bind_buffer: *fn(u32, u32),
  buffer_data: *fn(u32, isize, rawptr, u32),
  delete_buffers: *fn(i32, *const u32),
  enable_vertex_attribute: *fn(u32),
  vertex_attribute: *fn(u32, i32, u32, u8, i32, rawptr),
  draw_arrays: *fn(u32, i32, i32),
  read_pixels: *fn(i32, i32, i32, i32, u32, u32, rawptr),
}
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L48)

```dyn
pub struct LoadResult { api: Api, missing: []const u8, ok: bool }
```

[Source](../../compiler/vendor/opengl/opengl.dyn#L56)

Loader must be usable synchronously with a current GL 3.3+ core context.
Failure returns no callable table and identifies the first missing function.

```dyn
pub fn load(loader: Loader) LoadResult
```
