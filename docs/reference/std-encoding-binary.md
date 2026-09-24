# std/encoding/binary

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-foundation/main.dyn](../../tests/sdk-foundation/main.dyn)
- [tests/stdlib-data/main.dyn](../../tests/stdlib-data/main.dyn)
- [tests/stdlib-mem-extra/main.dyn](../../tests/stdlib-mem-extra/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/encoding/binary/binary.dyn

[Source](../../compiler/std/encoding/binary/binary.dyn#L3)

```dyn
pub struct Decode { value: u64, consumed: usize, ok: bool }
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L5)

```dyn
pub fn load_u16_le(source: []const u8) u16
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L9)

```dyn
pub fn load_u32_le(source: []const u8) u32
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L14)

```dyn
pub fn load_u64_le(source: []const u8) u64
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L18)

```dyn
pub fn load_u16_be(source: []const u8) u16
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L22)

```dyn
pub fn load_u32_be(source: []const u8) u32
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L27)

```dyn
pub fn load_u64_be(source: []const u8) u64
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L32)

```dyn
pub fn store_u16_le(destination: []u8, value: u16)
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L36)

```dyn
pub fn store_u32_le(destination: []u8, value: u32)
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L41)

```dyn
pub fn store_u64_le(destination: []u8, value: u64)
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L46)

```dyn
pub fn store_u16_be(destination: []u8, value: u16)
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L50)

```dyn
pub fn store_u32_be(destination: []u8, value: u32)
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L55)

```dyn
pub fn store_u64_be(destination: []u8, value: u64)
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L61)

```dyn
pub fn uleb128_size(value: u64) usize
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L67)

```dyn
pub fn uleb128_encode(destination: []u8, value: u64) []u8
```

[Source](../../compiler/std/encoding/binary/binary.dyn#L79)

```dyn
pub fn uleb128_decode(source: []const u8) Decode
```
