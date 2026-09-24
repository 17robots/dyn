# std/encoding/json

[Reference index](README.md)

## Storage and lifetime

DOM nodes borrow their arena; constructed text and keys borrow caller slices. Each node has at most one parent. Public linkage fields are read-only to callers. There is no implicit detach or clone.

## Failure behavior

Invalid attachment, cycles and reparenting return false without mutating links or keys. Capacity failure returns nil/failed result. Check the specific parser result before retaining nodes.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/json-dom/main.dyn](../../tests/json-dom/main.dyn)
- [tests/sdk-api-contracts/main.dyn](../../tests/sdk-api-contracts/main.dyn)
- [tests/sdk-data/main.dyn](../../tests/sdk-data/main.dyn)
- [tests/sdk-hardening/main.dyn](../../tests/sdk-hardening/main.dyn)
- [tests/stdlib-app/main.dyn](../../tests/stdlib-app/main.dyn)
- [tests/stdlib-contracts/main.dyn](../../tests/stdlib-contracts/main.dyn)

Reviewed behavioral fixtures: [tests/json-dom/main.dyn](../../tests/json-dom/main.dyn), [tests/sdk-api-contracts/main.dyn](../../tests/sdk-api-contracts/main.dyn)

## Declarations and source contracts

## Source: compiler/std/encoding/json/json.dyn

[Source](../../compiler/std/encoding/json/json.dyn#L7)

```dyn
pub const KindNull: u8 = 0
```

[Source](../../compiler/std/encoding/json/json.dyn#L8)

```dyn
pub const KindBool: u8 = 1
```

[Source](../../compiler/std/encoding/json/json.dyn#L9)

```dyn
pub const KindNumber: u8 = 2
```

[Source](../../compiler/std/encoding/json/json.dyn#L10)

```dyn
pub const KindString: u8 = 3
```

[Source](../../compiler/std/encoding/json/json.dyn#L11)

```dyn
pub const KindArray: u8 = 4
```

[Source](../../compiler/std/encoding/json/json.dyn#L12)

```dyn
pub const KindObject: u8 = 5
```

[Source](../../compiler/std/encoding/json/json.dyn#L14)

```dyn
pub enum TokenKind {
  End, Invalid, Null, Bool, Number, String,
  ArrayBegin, ArrayEnd, ObjectBegin, ObjectEnd, Colon, Comma,
}
```

[Source](../../compiler/std/encoding/json/json.dyn#L19)

```dyn
pub enum ErrorKind { None, Syntax, TrailingData, Capacity }
```

[Source](../../compiler/std/encoding/json/json.dyn#L21)

```dyn
pub struct Tokenizer { source: []const u8, offset: usize }
```

[Source](../../compiler/std/encoding/json/json.dyn#L22)

```dyn
pub struct Token { kind: TokenKind, text: []const u8, offset: usize }
```

[Source](../../compiler/std/encoding/json/json.dyn#L24)

```dyn
pub struct Value {
  kind: u8,
  boolean: bool,
  text: []const u8,
  key: []const u8,
  first: *Value,
  last: *Value,
  next: *Value,
  // Intrusive membership; mutate tree links only through add/add_member.
  parent: *Value,
}
```

[Source](../../compiler/std/encoding/json/json.dyn#L36)

```dyn
pub struct ParseResult { root: *Value, error_offset: usize, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/encoding/json/json.dyn#L38)

```dyn
pub fn tokenizer(source: []const u8) Tokenizer
```

[Source](../../compiler/std/encoding/json/json.dyn#L42)

```dyn
pub fn token_next(state: *Tokenizer) Token
```

[Source](../../compiler/std/encoding/json/json.dyn#L221)

```dyn
pub fn valid(source: []const u8) bool
```

[Source](../../compiler/std/encoding/json/json.dyn#L228)

```dyn
pub fn write_string(destination: []u8, source: []const u8) []u8
```

[Source](../../compiler/std/encoding/json/json.dyn#L422)

Nodes, decoded strings, and object keys live in arena. Number text borrows source.
Source must outlive uses of number text; all nodes expire when arena storage resets.
Failure rewinds only this call's allocations and distinguishes capacity from syntax.

```dyn
pub fn parse(arena: *memory.Arena, source: []const u8) ParseResult
```

[Source](../../compiler/std/encoding/json/json.dyn#L437)

```dyn
pub fn make_null(arena: *memory.Arena) *Value
```

[Source](../../compiler/std/encoding/json/json.dyn#L438)

```dyn
pub fn make_bool(arena: *memory.Arena, value: bool) *Value
```

[Source](../../compiler/std/encoding/json/json.dyn#L444)

Retains text as a borrowed view; caller keeps it alive.

```dyn
pub fn make_number(arena: *memory.Arena, text: []const u8) *Value
```

[Source](../../compiler/std/encoding/json/json.dyn#L452)

Retains text as a borrowed view; caller keeps it alive.

```dyn
pub fn make_string(arena: *memory.Arena, text: []const u8) *Value
```

[Source](../../compiler/std/encoding/json/json.dyn#L457)

```dyn
pub fn make_array(arena: *memory.Arena) *Value
```

[Source](../../compiler/std/encoding/json/json.dyn#L458)

```dyn
pub fn make_object(arena: *memory.Arena) *Value
```

[Source](../../compiler/std/encoding/json/json.dyn#L473)

```dyn
pub fn add(parent: *Value, child: *Value) bool
```

[Source](../../compiler/std/encoding/json/json.dyn#L478)

```dyn
pub fn add_member(parent: *Value, key: []const u8, child: *Value) bool
```

[Source](../../compiler/std/encoding/json/json.dyn#L485)

```dyn
pub fn object_get(object: *const Value, key: []const u8) *const Value
```

[Source](../../compiler/std/encoding/json/json.dyn#L495)

```dyn
pub fn array_length(array: *const Value) usize
```

[Source](../../compiler/std/encoding/json/json.dyn#L506)

```dyn
pub fn array_get(array: *const Value, index: usize) *const Value
```

[Source](../../compiler/std/encoding/json/json.dyn#L518)

```dyn
pub fn is_null(value: *const Value) bool
```

[Source](../../compiler/std/encoding/json/json.dyn#L519)

```dyn
pub fn is_bool(value: *const Value) bool
```

[Source](../../compiler/std/encoding/json/json.dyn#L520)

```dyn
pub fn is_number(value: *const Value) bool
```

[Source](../../compiler/std/encoding/json/json.dyn#L521)

```dyn
pub fn is_string(value: *const Value) bool
```

[Source](../../compiler/std/encoding/json/json.dyn#L522)

```dyn
pub fn is_array(value: *const Value) bool
```

[Source](../../compiler/std/encoding/json/json.dyn#L523)

```dyn
pub fn is_object(value: *const Value) bool
```

[Source](../../compiler/std/encoding/json/json.dyn#L577)

```dyn
pub fn encode(destination: []u8, value: *const Value) []u8
```

[Source](../../compiler/std/encoding/json/json.dyn#L621)

```dyn
pub fn encode_pretty(destination: []u8, value: *const Value, indent: usize) []u8
```

[Source](../../compiler/std/encoding/json/json.dyn#L731)

```dyn
pub fn write(destination: stream.Writer, value: *const Value) stream.Result
```
