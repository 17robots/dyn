# std/unicode/text

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-storage-contracts/main.dyn](../../tests/sdk-storage-contracts/main.dyn)
- [tests/sdk-unicode-text/main.dyn](../../tests/sdk-unicode-text/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/unicode/text/graphemes.dyn

[Source](../../compiler/std/unicode/text/graphemes.dyn#L1)

```dyn
pub struct Graphemes { source: []const u8, offset: usize, error: ErrorKind }
```

[Source](../../compiler/std/unicode/text/graphemes.dyn#L2)

```dyn
pub struct GraphemeResult { text: []const u8, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/unicode/text/graphemes.dyn#L3)

```dyn
pub fn graphemes(source: []const u8) Graphemes
```

[Source](../../compiler/std/unicode/text/graphemes.dyn#L7)

Extended grapheme clusters, UAX #29 Unicode 17 default rules. Invalid UTF-8 is
a sticky error; End has ok=false/error=None. Returned slices borrow source.

```dyn
pub fn next_grapheme(state: *Graphemes) GraphemeResult
```

## Source: compiler/std/unicode/text/tables_generated.dyn

## Source: compiler/std/unicode/text/text.dyn

[Source](../../compiler/std/unicode/text/text.dyn#L3)

```dyn
pub const UnicodeVersion: []const u8 = "17.0.0"
```

[Source](../../compiler/std/unicode/text/text.dyn#L4)

```dyn
pub enum ErrorKind { None, InvalidUtf8, Capacity, Overlap }
```

[Source](../../compiler/std/unicode/text/text.dyn#L5)

```dyn
pub struct Result { written: usize, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/unicode/text/text.dyn#L6)

```dyn
pub enum Form { NFD, NFC, NFKD, NFKC }
```

[Source](../../compiler/std/unicode/text/text.dyn#L7)

```dyn
pub enum Category { Cn, Lu, Ll, Lt, Lm, Lo, Mn, Mc, Me, Nd, Nl, No, Pc, Pd, Ps, Pe, Pi, Pf, Po, Sm, Sc, Sk, So, Zs, Zl, Zp, Cc, Cf, Cs, Co }
```

[Source](../../compiler/std/unicode/text/text.dyn#L18)

```dyn
pub fn category(codepoint: u32) Category
```

[Source](../../compiler/std/unicode/text/text.dyn#L51)

```dyn
pub fn combining_class(codepoint: u32) u32
```

[Source](../../compiler/std/unicode/text/text.dyn#L52)

```dyn
pub fn identifier_start(codepoint: u32) bool
```

[Source](../../compiler/std/unicode/text/text.dyn#L53)

```dyn
pub fn identifier_continue(codepoint: u32) bool
```

[Source](../../compiler/std/unicode/text/text.dyn#L54)

```dyn
pub fn whitespace(codepoint: u32) bool
```

[Source](../../compiler/std/unicode/text/text.dyn#L67)

Locale-independent full default case folding, without normalization.
Overlap is rejected before writing. Other failures report a complete UTF-8 prefix.

```dyn
pub fn case_fold(destination: []u8, source: []const u8) Result
```

[Source](../../compiler/std/unicode/text/text.dyn#L98)

Work is split into equal decomposition/reordering buffers. Each half needs
one slot per fully decomposed scalar. Input/output/work must not overlap.
Errors may modify storage; written reports only the complete output prefix.

```dyn
pub fn normalize(destination: []u8, source: []const u8, form: Form, work: []u32) Result
```
