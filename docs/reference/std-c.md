# std/c

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-buffer-contracts/main.dyn](../../tests/sdk-buffer-contracts/main.dyn)
- [tests/stdlib-c/main.dyn](../../tests/stdlib-c/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/c/browser.dyn

Target gate: `#target(kernel: browser)`

[Source](../../compiler/std/c/browser.dyn#L3)

wasm32 Basic C ABI.

```dyn
pub type long = i32
```

[Source](../../compiler/std/c/browser.dyn#L4)

```dyn
pub type unsigned_long = u32
```

[Source](../../compiler/std/c/browser.dyn#L5)

```dyn
pub type char = i8
```

## Source: compiler/std/c/c.dyn

[Source](../../compiler/std/c/c.dyn#L5)

C ABI names. Target files select long width and plain-char signedness. No wrappers,
conversions, allocation, or distinct-type friction at foreign call sites.

```dyn
pub type signed_char = i8
```

[Source](../../compiler/std/c/c.dyn#L6)

```dyn
pub type unsigned_char = u8
```

[Source](../../compiler/std/c/c.dyn#L7)

```dyn
pub type short = i16
```

[Source](../../compiler/std/c/c.dyn#L8)

```dyn
pub type unsigned_short = u16
```

[Source](../../compiler/std/c/c.dyn#L9)

```dyn
pub type int = i32
```

[Source](../../compiler/std/c/c.dyn#L10)

```dyn
pub type unsigned_int = u32
```

[Source](../../compiler/std/c/c.dyn#L11)

```dyn
pub type long_long = i64
```

[Source](../../compiler/std/c/c.dyn#L12)

```dyn
pub type unsigned_long_long = u64
```

[Source](../../compiler/std/c/c.dyn#L13)

```dyn
pub type float = f32
```

[Source](../../compiler/std/c/c.dyn#L14)

```dyn
pub type double = f64
```

[Source](../../compiler/std/c/c.dyn#L15)

```dyn
pub type size = usize
```

[Source](../../compiler/std/c/c.dyn#L16)

```dyn
pub type ptrdiff = isize
```

[Source](../../compiler/std/c/c.dyn#L17)

```dyn
pub type intptr = isize
```

[Source](../../compiler/std/c/c.dyn#L18)

```dyn
pub type uintptr = usize
```

[Source](../../compiler/std/c/c.dyn#L19)

```dyn
pub type intmax = i64
```

[Source](../../compiler/std/c/c.dyn#L20)

```dyn
pub type uintmax = u64
```

[Source](../../compiler/std/c/c.dyn#L21)

```dyn
pub type string = *const u8
```

[Source](../../compiler/std/c/c.dyn#L22)

```dyn
pub type mutable_string = *u8
```

[Source](../../compiler/std/c/c.dyn#L23)

```dyn
pub type pointer = rawptr
```

[Source](../../compiler/std/c/c.dyn#L25)

```dyn
pub enum ErrorKind { None, InvalidInput, Capacity, Overflow, Unterminated }
```

[Source](../../compiler/std/c/c.dyn#L27)

```dyn
pub struct StringResult {
  error: ErrorKind,
  required: usize,
  value: string,
  ok: bool,
}
```

[Source](../../compiler/std/c/c.dyn#L34)

```dyn
pub struct BytesResult { value: []const u8, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/c/c.dyn#L37)

Bounded scan: never reads beyond `maximum`; callers retain source ownership.

```dyn
pub fn string_length(value: string, maximum: usize) usize
```

[Source](../../compiler/std/c/c.dyn#L45)

```dyn
pub fn bytes_from_string(value: string, maximum: usize) BytesResult
```

[Source](../../compiler/std/c/c.dyn#L52)

```dyn
pub fn errno_from_result(value: isize) isize
```

[Source](../../compiler/std/c/c.dyn#L56)

```dyn
pub fn succeeded(value: isize) bool
```

[Source](../../compiler/std/c/c.dyn#L60)

Copies bytes and appends NUL. Embedded NUL is invalid; arbitrary overlap is
supported. Failure leaves destination untouched. Required includes the NUL.

```dyn
pub fn string_from_bytes(destination: []u8, source: []const u8) StringResult
```

[Source](../../compiler/std/c/c.dyn#L71)

Arena-owned C string; failure rewinds only this operation's allocation.

```dyn
pub fn string_from_arena(arena: *memory.Arena, source: []const u8) StringResult
```

## Source: compiler/std/c/char_linux_aarch64.dyn

Target gate: `#target(kernel: linux, arch: aarch64)`

[Source](../../compiler/std/c/char_linux_aarch64.dyn#L3)

Default C ABI; -fsigned-char requires an explicit binding override.

```dyn
pub type char = u8
```

## Source: compiler/std/c/char_linux_x86_64.dyn

Target gate: `#target(kernel: linux, arch: x86_64)`

[Source](../../compiler/std/c/char_linux_x86_64.dyn#L3)

Default C ABI; -funsigned-char requires an explicit binding override.

```dyn
pub type char = i8
```

## Source: compiler/std/c/darwin.dyn

Target gate: `#target(kernel: darwin)`

[Source](../../compiler/std/c/darwin.dyn#L2)

```dyn
pub type long = i64
```

[Source](../../compiler/std/c/darwin.dyn#L3)

```dyn
pub type unsigned_long = u64
```

[Source](../../compiler/std/c/darwin.dyn#L4)

```dyn
pub type char = i8
```

## Source: compiler/std/c/linux.dyn

Target gate: `#target(kernel: linux)`

[Source](../../compiler/std/c/linux.dyn#L2)

```dyn
pub type long = i64
```

[Source](../../compiler/std/c/linux.dyn#L3)

```dyn
pub type unsigned_long = u64
```

## Source: compiler/std/c/wasi.dyn

Target gate: `#target(kernel: wasi)`

[Source](../../compiler/std/c/wasi.dyn#L2)

```dyn
pub type long = i32
```

[Source](../../compiler/std/c/wasi.dyn#L3)

```dyn
pub type unsigned_long = u32
```

[Source](../../compiler/std/c/wasi.dyn#L4)

```dyn
pub type char = i8
```

## Source: compiler/std/c/windows.dyn

Target gate: `#target(kernel: windows)`

[Source](../../compiler/std/c/windows.dyn#L2)

```dyn
pub type long = i32
```

[Source](../../compiler/std/c/windows.dyn#L3)

```dyn
pub type unsigned_long = u32
```

[Source](../../compiler/std/c/windows.dyn#L4)

```dyn
pub type char = i8
```
