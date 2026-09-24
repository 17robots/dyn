# std/compress/deflate

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/deflate-encode/main.dyn](../../tests/deflate-encode/main.dyn)
- [tests/sdk-depth/main.dyn](../../tests/sdk-depth/main.dyn)
- [tests/stdlib-depth/main.dyn](../../tests/stdlib-depth/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/compress/deflate/deflate.dyn

[Source](../../compiler/std/compress/deflate/deflate.dyn#L3)

```dyn
pub struct Result { written: usize, consumed: usize, ok: bool }
```

[Source](../../compiler/std/compress/deflate/deflate.dyn#L7)

Both buffers and this state must remain alive and disjoint while reading.
1024 input bytes and 33026 history bytes suffice regardless of stream length.
Smaller buffers work for streams whose headers/history fit; capacity is explicit.

```dyn
pub struct Decoder {
  engine: InflateState,
  source_reader: stream.Reader,
  compressed_storage: []u8,
  output_storage: []u8,
  compressed_used: usize,
  offset: usize,
  source_ended: bool,
  finished: bool,
  error: isize,
  gzip: bool,
  phase: u8,
  flags: u8,
  extra: usize,
  header_crc: u32,
  checksum: u32,
  member_size: u32,
  members: usize,
}
```

[Source](../../compiler/std/compress/deflate/deflate.dyn#L27)

```dyn
pub fn decoder(input: stream.Reader, compressed_bytes: []u8, history: []u8) Decoder
```

[Source](../../compiler/std/compress/deflate/deflate.dyn#L153)

```dyn
pub fn decoder_reader(state: *Decoder) stream.Reader
```

[Source](../../compiler/std/compress/deflate/deflate.dyn#L159)

Emits byte-aligned stored DEFLATE blocks. Call with final=false for each
intermediate chunk and final=true for the last; concatenate caller buffers.

```dyn
pub fn deflate_stored_chunk(destination: []u8, input: []const u8, final: bool) Result
```

[Source](../../compiler/std/compress/deflate/deflate.dyn#L325)

```dyn
pub fn deflate_fixed_chunk(destination: []u8, input: []const u8, final: bool,
                           scratch: []usize) Result
```

[Source](../../compiler/std/compress/deflate/deflate.dyn#L332)

Dynamic-Huffman block using deterministic RFC 1951 trees and the same LZ77
matcher. Deterministic trees keep compile/runtime cost bounded and predictable.

```dyn
pub fn deflate_dynamic_chunk(destination: []u8, input: []const u8, final: bool,
                             scratch: []usize) Result
```

[Source](../../compiler/std/compress/deflate/deflate.dyn#L446)

State retains block trees and bit position. Input/output prefixes must remain
unchanged and grow monotonically until completion; no allocation occurs here.

```dyn
pub struct InflateState {
  reader: Bits, literal: Huffman, distance: Huffman,
  stage: u8, final: u32, stored: usize, written: usize, error: isize, output_full: bool,
}
```

[Source](../../compiler/std/compress/deflate/deflate.dyn#L519)

```dyn
pub fn resume(state: *InflateState, destination: []u8, input: []const u8) Result
```

[Source](../../compiler/std/compress/deflate/deflate.dyn#L591)

RFC 1951 stored, fixed-Huffman, and dynamic-Huffman DEFLATE.

```dyn
pub fn inflate(destination: []u8, input: []const u8) Result
```

[Source](../../compiler/std/compress/deflate/deflate.dyn#L616)

A single gzip member. Prefixes remain borrowed, as for InflateState.

```dyn
pub struct GzipState { engine: InflateState, stage: u8, at: usize, flags: u8, error: isize }
```

[Source](../../compiler/std/compress/deflate/deflate.dyn#L617)

```dyn
pub fn resume_gzip(state: *GzipState, destination: []u8, input: []const u8) Result
```

[Source](../../compiler/std/compress/deflate/deflate.dyn#L663)

RFC 1952 single member; consumed identifies any following member/trailing data.

```dyn
pub fn gunzip_internal(destination: []u8, input: []const u8) Result
```
