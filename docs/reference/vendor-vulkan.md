# vendor/vulkan

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-vulkan/main.dyn](../../tests/sdk-vulkan/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/vendor/vulkan/raw_generated.dyn

## Source: compiler/vendor/vulkan/vulkan.dyn

[Source](../../compiler/vendor/vulkan/vulkan.dyn#L6)

Vulkan deliberately exposes one stable loader seam. Applications generate typed
commands/structures for the header version they target instead of coupling SDK releases.

```dyn
pub type Instance = rawptr
```

[Source](../../compiler/vendor/vulkan/vulkan.dyn#L7)

```dyn
pub type Procedure = rawptr
```

[Source](../../compiler/vendor/vulkan/vulkan.dyn#L8)

```dyn
pub struct ProcedureResult { value: Procedure, ok: bool }
```

[Source](../../compiler/vendor/vulkan/vulkan.dyn#L10)

```dyn
pub fn make_version(variant, major, minor, patch: u32) u32
```

[Source](../../compiler/vendor/vulkan/vulkan.dyn#L13)

```dyn
pub fn version_variant(version: u32) u32
```

[Source](../../compiler/vendor/vulkan/vulkan.dyn#L14)

```dyn
pub fn version_major(version: u32) u32
```

[Source](../../compiler/vendor/vulkan/vulkan.dyn#L15)

```dyn
pub fn version_minor(version: u32) u32
```

[Source](../../compiler/vendor/vulkan/vulkan.dyn#L16)

```dyn
pub fn version_patch(version: u32) u32
```

[Source](../../compiler/vendor/vulkan/vulkan.dyn#L19)

name_buffer receives a temporary NUL-terminated copy. Returned function is loader-owned.

```dyn
pub fn procedure(instance: Instance, name: []const u8, name_buffer: []u8) ProcedureResult
```

[Source](../../compiler/vendor/vulkan/vulkan.dyn#L25)

```dyn
pub fn global_procedure(name: []const u8, buffer: []u8) ProcedureResult
```
