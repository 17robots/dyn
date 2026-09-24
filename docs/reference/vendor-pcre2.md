# vendor/pcre2

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

No direct checked-in Dyn fixture reference found; generated/transitive tests may exist. This is a review gap, not a declaration of coverage.

Reviewed behavioral fixtures: [projects/regex-example/main.dyn](../../projects/regex-example/main.dyn), [tests/vendor-packages.py](../../tests/vendor-packages.py)

## Declarations and source contracts

## Source: compiler/vendor/pcre2/pcre2.dyn

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L3)

PCRE2 8-bit API. Compiled patterns and match data are provider-owned.

```dyn
pub type Pattern = rawptr
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L4)

```dyn
pub type MatchData = rawptr
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L5)

```dyn
pub const Utf: u32 = 524288
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L6)

```dyn
pub const Ucp: u32 = 131072
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L7)

```dyn
pub const Caseless: u32 = 8
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L8)

```dyn
pub const NoMatch: i32 = -1
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L9)

```dyn
pub struct CompileResult { pattern: Pattern, code: i32, offset: usize, ok: bool }
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L10)

```dyn
pub struct MatchResult { code: i32, matched: bool, ok: bool }
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L11)

```dyn
pub struct Span { start: usize, end: usize, set: bool }
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L12)

```dyn
pub fn compile_owned(pattern: []const u8, options: u32) CompileResult
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L19)

```dyn
pub fn pattern_destroy_owned(pattern: Pattern)
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L20)

```dyn
pub fn match_data_create_owned(pattern: Pattern) MatchData
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L21)

```dyn
pub fn match_data_destroy_owned(data: MatchData)
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L24)

Subject borrowed for call; offsets refer to caller subject. Match data is mutable
and thread-confined. Captures are meaningful only after a successful match.

```dyn
pub fn match(pattern: Pattern, data: MatchData, subject: []const u8, start: usize) MatchResult
```

[Source](../../compiler/vendor/pcre2/pcre2.dyn#L31)

```dyn
pub fn capture(data: MatchData, index: u32) Span
```
