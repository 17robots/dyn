# vendor/box2d

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/box2d-example/main.dyn](../../projects/box2d-example/main.dyn), [tests/vendor-extra.py](../../tests/vendor-extra.py)

## Declarations and source contracts

## Source: compiler/vendor/box2d/box2d.dyn

[Source](../../compiler/vendor/box2d/box2d.dyn#L5)

Box2D 3.1.1 C ABI adapter. Provider owns worlds, bodies and shapes.
Destroy a world to destroy all its children; IDs are generation-checked.
Do not use one world concurrently. IDs are not stable serialized objects.

```dyn
pub type World = u32
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L6)

```dyn
pub type Body = u64
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L7)

```dyn
pub type Shape = u64
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L8)

```dyn
pub struct Position { x: f32, y: f32, ok: bool }
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L9)

```dyn
pub extern fn create_owned "dyn_b2_world_create"(gravity_x: f32, gravity_y: f32) World
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L10)

```dyn
pub extern fn destroy_owned "dyn_b2_world_destroy"(world: World) bool
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L12)

dt must be finite, >0 and <=1 second; substeps 1..64.

```dyn
pub extern fn step "dyn_b2_step"(world: World, dt: f32, substeps: i32) bool
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L13)

```dyn
pub extern fn body_create "dyn_b2_body"(world: World, x: f32, y: f32, dynamic: bool) Body
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L14)

```dyn
pub extern fn body_destroy "dyn_b2_body_destroy"(body: Body) bool
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L16)

Positive finite half-extents and nonnegative finite density. Body owns shape.

```dyn
pub extern fn box_create "dyn_b2_box"(body: Body, half_width: f32, half_height: f32, density: f32) Shape
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L17)

```dyn
pub fn position(body: Body) Position
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L24)

```dyn
pub type Joint = u64
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L25)

```dyn
pub extern fn circle_create "dyn_b2_circle"(body: Body, radius: f32, density: f32) Shape
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L27)

Rigid distance joint anchored at body origins; bodies must share a world.

```dyn
pub extern fn distance_joint "dyn_b2_distance"(first: Body, second: Body, length: f32) Joint
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L28)

```dyn
pub extern fn joint_destroy "dyn_b2_joint_destroy"(joint: Joint) bool
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L29)

```dyn
pub extern fn contact_events "dyn_b2_events"(shape: Shape, enabled: bool) bool
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L31)

Read after step and before modifying the world. -1 means invalid world.

```dyn
pub extern fn contact_count "dyn_b2_contact_count"(world: World, begin: bool) i32
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L32)

```dyn
pub struct Contact { first: Shape, second: Shape, ok: bool }
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L33)

```dyn
pub fn contact(world: World, begin: bool, index: i32) Contact
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L36)

```dyn
pub struct Query { total: usize, written: usize, ok: bool }
```

[Source](../../compiler/vendor/box2d/box2d.dyn#L39)

Broad-phase AABB candidates, not exact geometry overlap. Output order is
unspecified. total may exceed capacity; written reports the copied prefix.

```dyn
pub fn query(world: World, x0: f32, y0: f32, x1: f32, y1: f32, output: []Shape) Query
```
