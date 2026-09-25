# std/encoding/base64

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-buffer-contracts/main.dyn](../../tests/sdk-buffer-contracts/main.dyn)
- [tests/sdk-foundation/main.dyn](../../tests/sdk-foundation/main.dyn)
- [tests/stdlib-data/main.dyn](../../tests/stdlib-data/main.dyn)

Reviewed behavioral fixtures: [tests/sdk-buffer-contracts/main.dyn](../../tests/sdk-buffer-contracts/main.dyn)

## Declarations and source contracts

## Source: compiler/std/encoding/base64/base64.dyn

[Source](../../compiler/std/encoding/base64/base64.dyn#L3)

```dyn
pub type Result = codec.Result
```

[Source](../../compiler/std/encoding/base64/base64.dyn#L4)

```dyn
pub type ErrorKind = codec.ErrorKind
```

[Source](../../compiler/std/encoding/base64/base64.dyn#L9)

```dyn
pub fn encoded_size(source_size: usize) usize
```

[Source](../../compiler/std/encoding/base64/base64.dyn#L17)

```dyn
pub fn encode(destination: []u8, source: []const u8) Result
```

[Source](../../compiler/std/encoding/base64/base64.dyn#L97)

```dyn
pub fn decode(destination: []u8, source: []const u8) Result
```

[Source](../../compiler/std/encoding/base64/base64.dyn#L108)

Validates the complete input and reports exact decoded bytes. Failure leaves
output unchanged; true with zero bytes is a valid empty encoding.

```dyn
pub fn decoded_size(source: []const u8, output: *usize) bool
```
