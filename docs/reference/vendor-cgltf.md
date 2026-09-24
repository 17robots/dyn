# vendor/cgltf

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/cgltf-example/main.dyn](../../projects/cgltf-example/main.dyn), [tests/vendor-extra.py](../../tests/vendor-extra.py)

## Declarations and source contracts

## Source: compiler/vendor/cgltf/cgltf.dyn

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L5)

cgltf 1.15. Provider owns parsed model; keep input bytes alive until destroy.
In particular GLB binary buffers borrow input. Handles must not be copied for ownership.

```dyn
pub type Model = rawptr
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L6)

```dyn
pub struct Result { value: Model, code: i32, ok: bool }
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L7)

```dyn
pub fn parse_owned(bytes: []const u8) Result
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L12)

```dyn
pub fn destroy_owned(model: Model)
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L13)

```dyn
pub fn validate(model: Model) bool
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L16)

Loads only embedded data URIs/GLB buffers, never external files. -2 rejects an
unresolved external resource before loading any buffers. Other codes are cgltf_result.

```dyn
pub fn load_embedded(model: Model) i32
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L17)

```dyn
pub extern fn node_count "dyn_cgltf_nodes"(model: Model) usize
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L18)

```dyn
pub extern fn accessor_count "dyn_cgltf_accessors"(model: Model) usize
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L20)

Non-sparse accessors only. Output borrows caller storage; model remains owned.

```dyn
pub fn read_float(model: Model, accessor: usize, element: usize, output: []f32) bool
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L33)

External resource loading is explicit: inspect URI, load with application
policy, then attach. Attached bytes are borrowed through model destruction.
Attach only once per buffer; never frees or replaces already loaded storage.

```dyn
pub extern fn buffer_count "dyn_cgltf_buffers"(model: Model) usize
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L34)

```dyn
pub extern fn buffer_size "dyn_cgltf_buffer_size"(model: Model, index: usize) usize
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L35)

```dyn
pub fn attach_buffer(model: Model, index: usize, bytes: []const u8) bool
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L39)

```dyn
pub fn buffer_uri(model: Model, index: usize, maximum: usize) []const u8
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L43)

```dyn
pub const Position: i32 = 1
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L44)

```dyn
pub const Normal: i32 = 2
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L45)

```dyn
pub const Tangent: i32 = 3
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L46)

```dyn
pub const Texcoord: i32 = 4
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L47)

```dyn
pub const Color: i32 = 5
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L48)

```dyn
pub const Joints: i32 = 6
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L49)

```dyn
pub const Weights: i32 = 7
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L50)

```dyn
pub const Triangles: i32 = 5
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L51)

```dyn
pub extern fn mesh_count "dyn_cgltf_meshes"(model: Model) usize
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L52)

```dyn
pub extern fn material_count "dyn_cgltf_materials"(model: Model) usize
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L53)

```dyn
pub extern fn primitive_count "dyn_cgltf_primitives"(model: Model, mesh: usize) usize
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L55)

Optional index results use -1 for absent/invalid. Attribute set is usually 0.

```dyn
pub extern fn attribute "dyn_cgltf_attribute"(model: Model, mesh: usize, primitive: usize, kind: i32, set: i32) i64
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L56)

```dyn
pub extern fn indices "dyn_cgltf_indices"(model: Model, mesh: usize, primitive: usize) i64
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L57)

```dyn
pub extern fn material "dyn_cgltf_material"(model: Model, mesh: usize, primitive: usize) i64
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L58)

```dyn
pub extern fn topology "dyn_cgltf_topology"(model: Model, mesh: usize, primitive: usize) i32
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L59)

```dyn
pub extern fn element_count "dyn_cgltf_elements"(model: Model, accessor: usize) usize
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L60)

```dyn
pub extern fn node_mesh "dyn_cgltf_node_mesh"(model: Model, node: usize) i64
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L61)

```dyn
pub struct Index { value: u32, ok: bool }
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L62)

```dyn
pub fn read_index(model: Model, accessor: usize, element: usize) Index
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L66)

Column-major world matrix and RGBA base factor, copied into caller storage.

```dyn
pub fn world_transform(model: Model, node: usize, output: []f32) bool
```

[Source](../../compiler/vendor/cgltf/cgltf.dyn#L69)

```dyn
pub fn base_color(model: Model, material: usize, output: []f32) bool
```
