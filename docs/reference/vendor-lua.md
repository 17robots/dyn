# vendor/lua

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/lua-example/main.dyn](../../projects/lua-example/main.dyn), [tests/vendor-packages.py](../../tests/vendor-packages.py)

## Declarations and source contracts

## Source: compiler/vendor/lua/lua.dyn

[Source](../../compiler/vendor/lua/lua.dyn#L4)

Lua 5.4 default ABI (64-bit integers, double numbers). State is provider-owned.
No standard libraries are opened automatically. This is not a sandbox.

```dyn
pub type State = rawptr
```

[Source](../../compiler/vendor/lua/lua.dyn#L5)

```dyn
pub struct Result { code: i32, ok: bool }
```

[Source](../../compiler/vendor/lua/lua.dyn#L6)

```dyn
pub struct IntegerResult { value: i64, ok: bool }
```

[Source](../../compiler/vendor/lua/lua.dyn#L7)

```dyn
pub struct BytesResult { value: []const u8, ok: bool }
```

[Source](../../compiler/vendor/lua/lua.dyn#L8)

```dyn
pub fn create_owned() State
```

[Source](../../compiler/vendor/lua/lua.dyn#L9)

```dyn
pub fn destroy_owned(state: State)
```

[Source](../../compiler/vendor/lua/lua.dyn#L10)

```dyn
pub fn stack_size(state: State) i32
```

[Source](../../compiler/vendor/lua/lua.dyn#L12)

Only remove values; never grow the stack through this API.

```dyn
pub fn pop(state: State, count: i32) bool
```

[Source](../../compiler/vendor/lua/lua.dyn#L20)

Text-only protected execution. On success leaves exactly one result (nil if
chunk returns none); on failure leaves one error. Earlier stack values survive.
Chunk source borrowed only during call. Caller must pop result/error.
Wrapper errors -1/-2 leave the stack unchanged.

```dyn
pub fn execute(state: State, source: []const u8) Result
```

[Source](../../compiler/vendor/lua/lua.dyn#L35)

```dyn
pub fn integer(state: State, index: i32) IntegerResult
```

[Source](../../compiler/vendor/lua/lua.dyn#L42)

Borrows an existing string while it remains on the stack and state stays alive.
No numeric conversion: that could allocate outside a protected Lua call.

```dyn
pub fn bytes(state: State, index: i32) BytesResult
```
