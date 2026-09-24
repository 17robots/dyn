# std/compress/gzip

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-depth/main.dyn](../../tests/sdk-depth/main.dyn)
- [tests/stdlib-depth/main.dyn](../../tests/stdlib-depth/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/compress/gzip/gzip.dyn

[Source](../../compiler/std/compress/gzip/gzip.dyn#L4)

```dyn
pub type Result = deflate.Result
```

[Source](../../compiler/std/compress/gzip/gzip.dyn#L5)

```dyn
pub type Decoder = deflate.Decoder
```

[Source](../../compiler/std/compress/gzip/gzip.dyn#L8)

One member; consumed identifies the next member or trailing data.

```dyn
pub fn decompress(destination: []u8, source: []const u8) Result
```

[Source](../../compiler/std/compress/gzip/gzip.dyn#L14)

Reads concatenated members through EOF, verifying every header/trailer.
Buffers borrow caller storage. 1024 input + 33026 history bytes suffice.
Returned output remains provisional until the reader reaches End.

```dyn
pub fn decoder(input: stream.Reader, compressed_bytes: []u8, history: []u8) Decoder
```

[Source](../../compiler/std/compress/gzip/gzip.dyn#L19)

```dyn
pub fn decoder_reader(state: *Decoder) stream.Reader
```
