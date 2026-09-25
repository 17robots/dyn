# std/strings

[Reference index](README.md)

## Storage and lifetime

View helpers borrow source. clone/join copy into destination or arena storage. split allocates only its table and still borrows source bytes for every element; keep both alive. An arena parameter does not imply a deep copy.

## Failure behavior

Inspect boolean/result fields for parsing and capacity failures. ASCII helpers operate on ASCII bytes; they do not implement Unicode case folding.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/path-contracts/main.dyn](../../tests/path-contracts/main.dyn)
- [tests/sdk-api-contracts/main.dyn](../../tests/sdk-api-contracts/main.dyn)
- [tests/sdk-behavior-stress/main.dyn](../../tests/sdk-behavior-stress/main.dyn)
- [tests/sdk-boundaries/main.dyn](../../tests/sdk-boundaries/main.dyn)
- [tests/sdk-buffer-contracts/main.dyn](../../tests/sdk-buffer-contracts/main.dyn)
- [tests/sdk-data/main.dyn](../../tests/sdk-data/main.dyn)
- [tests/sdk-depth/main.dyn](../../tests/sdk-depth/main.dyn)
- [tests/sdk-foundation/main.dyn](../../tests/sdk-foundation/main.dyn)
- [tests/sdk-memory-observation/main.dyn](../../tests/sdk-memory-observation/main.dyn)
- [tests/sdk-system/main.dyn](../../tests/sdk-system/main.dyn)
- [tests/stdlib-cli/main.dyn](../../tests/stdlib-cli/main.dyn)
- [tests/stdlib-foundation/main.dyn](../../tests/stdlib-foundation/main.dyn)
- [tests/stdlib-str/main.dyn](../../tests/stdlib-str/main.dyn)
- [tests/stdlib-testing/main.dyn](../../tests/stdlib-testing/main.dyn)
- [tests/stdlib-text-extra/main.dyn](../../tests/stdlib-text-extra/main.dyn)
- [tests/vendor-packages/curl/main.dyn](../../tests/vendor-packages/curl/main.dyn)

Reviewed behavioral fixtures: [tests/sdk-api-contracts/main.dyn](../../tests/sdk-api-contracts/main.dyn), [tests/sdk-behavior-stress/main.dyn](../../tests/sdk-behavior-stress/main.dyn), [tests/sdk-buffer-contracts/main.dyn](../../tests/sdk-buffer-contracts/main.dyn)

## Declarations and source contracts

## Source: compiler/std/strings/strings.dyn

[Source](../../compiler/std/strings/strings.dyn#L6)

```dyn
pub fn equal(left: []const u8, right: []const u8) bool
```

[Source](../../compiler/std/strings/strings.dyn#L8)

```dyn
pub fn find_byte(text: []const u8, byte: u8) isize
```

[Source](../../compiler/std/strings/strings.dyn#L10)

```dyn
pub fn find(text: []const u8, needle: []const u8) isize
```

[Source](../../compiler/std/strings/strings.dyn#L12)

```dyn
pub fn contains(text: []const u8, needle: []const u8) bool
```

[Source](../../compiler/std/strings/strings.dyn#L13)

```dyn
pub fn starts_with(text: []const u8, prefix: []const u8) bool
```

[Source](../../compiler/std/strings/strings.dyn#L14)

```dyn
pub fn ends_with(text: []const u8, suffix: []const u8) bool
```

[Source](../../compiler/std/strings/strings.dyn#L15)

```dyn
pub fn strip_prefix(text: []const u8, prefix: []const u8) []const u8
```

[Source](../../compiler/std/strings/strings.dyn#L19)

```dyn
pub fn strip_suffix(text: []const u8, suffix: []const u8) []const u8
```

[Source](../../compiler/std/strings/strings.dyn#L24)

```dyn
pub fn ascii_is_digit(byte: u8) bool
```

[Source](../../compiler/std/strings/strings.dyn#L25)

```dyn
pub fn ascii_is_alpha(byte: u8) bool
```

[Source](../../compiler/std/strings/strings.dyn#L28)

```dyn
pub fn ascii_is_whitespace(byte: u8) bool
```

[Source](../../compiler/std/strings/strings.dyn#L31)

```dyn
pub fn ascii_to_lower(byte: u8) u8
```

[Source](../../compiler/std/strings/strings.dyn#L35)

```dyn
pub fn ascii_to_upper(byte: u8) u8
```

[Source](../../compiler/std/strings/strings.dyn#L41)

Returns a borrowed view of text; no allocation or copy. Keep input storage alive and unchanged.

```dyn
pub fn trim(text: []const u8) []const u8
```

[Source](../../compiler/std/strings/strings.dyn#L56)

```dyn
pub fn parse_u64_base(text: []const u8, base: u8, output: *u64) bool
```

[Source](../../compiler/std/strings/strings.dyn#L72)

```dyn
pub fn parse_u64(text: []const u8, output: *u64) bool
```

[Source](../../compiler/std/strings/strings.dyn#L76)

```dyn
pub fn parse_i64(text: []const u8, output: *i64) bool
```

[Source](../../compiler/std/strings/strings.dyn#L95)

```dyn
pub struct Scanner { text: []const u8, offset: usize }
```

[Source](../../compiler/std/strings/strings.dyn#L96)

```dyn
pub fn scanner(text: []const u8) Scanner
```

[Source](../../compiler/std/strings/strings.dyn#L97)

```dyn
pub fn scanner_rest(state: *const Scanner) []const u8
```

[Source](../../compiler/std/strings/strings.dyn#L99)

```dyn
pub fn scan_until(state: *Scanner, delimiter: u8, output: *[]const u8) bool
```

[Source](../../compiler/std/strings/strings.dyn#L114)

```dyn
pub fn scan_field(state: *Scanner, output: *[]const u8) bool
```

[Source](../../compiler/std/strings/strings.dyn#L204)

Decimal syntax, rounded to binary64 with round-to-nearest/ties-to-even.
Overflow yields signed infinity; underflow preserves signed zero. Invalid
syntax leaves output unchanged. No heap allocations or locale dependence.

```dyn
pub fn parse_f64(text: []const u8, output: *f64) bool
```

[Source](../../compiler/std/strings/strings.dyn#L284)

```dyn
pub fn trim_left(text: []const u8) []const u8
```

[Source](../../compiler/std/strings/strings.dyn#L289)

```dyn
pub fn trim_right(text: []const u8) []const u8
```

[Source](../../compiler/std/strings/strings.dyn#L294)

```dyn
pub fn find_last_byte(text: []const u8, byte: u8) isize
```

[Source](../../compiler/std/strings/strings.dyn#L295)

```dyn
pub fn find_last(text: []const u8, needle: []const u8) isize
```

[Source](../../compiler/std/strings/strings.dyn#L296)

```dyn
pub fn scan_line(state: *Scanner, output: *[]const u8) bool
```

[Source](../../compiler/std/strings/strings.dyn#L302)

```dyn
pub enum ErrorKind { None, InvalidInput, Capacity, Overflow, Overlap }
```

[Source](../../compiler/std/strings/strings.dyn#L303)

```dyn
pub struct Result { value: []u8, error: ErrorKind, required: usize, ok: bool }
```

[Source](../../compiler/std/strings/strings.dyn#L304)

```dyn
pub struct SplitResult { values: [][]const u8, error: ErrorKind, required: usize, ok: bool }
```

[Source](../../compiler/std/strings/strings.dyn#L305)

```dyn
pub struct SizeResult { value: usize, error: ErrorKind, ok: bool }
```

[Source](../../compiler/std/strings/strings.dyn#L309)

Exact-capacity copies support overlap; failure leaves destination unchanged.
Copies into caller destination. Successful value borrows destination, not source. Inspect Result.ok.

```dyn
pub fn clone_into(destination: []u8, source: []const u8) Result
```

[Source](../../compiler/std/strings/strings.dyn#L315)

Copies bytes into arena. Result expires at applicable rewind/reset/release; input need not outlive it.

```dyn
pub fn clone(arena: *memory.Arena, source: []const u8) Result
```

[Source](../../compiler/std/strings/strings.dyn#L321)

```dyn
pub fn join_size(parts: [][]const u8, separator: []const u8) SizeResult
```

[Source](../../compiler/std/strings/strings.dyn#L336)

Output must not overlap any input bytes. Failure writes nothing.

```dyn
pub fn join_into(destination: []u8, parts: [][]const u8, separator: []const u8) Result
```

[Source](../../compiler/std/strings/strings.dyn#L350)

```dyn
pub fn join(arena: *memory.Arena, parts: [][]const u8, separator: []const u8) Result
```

[Source](../../compiler/std/strings/strings.dyn#L362)

```dyn
pub fn split_count(source: []const u8, separator: []const u8) SizeResult
```

[Source](../../compiler/std/strings/strings.dyn#L376)

Slice table and input bytes must occupy separate storage. Elements borrow source.
Empty fields, including the last, are retained. Failure changes no entries.
Writes views into caller slice-table storage. Elements still borrow source bytes; keep BOTH alive.

```dyn
pub fn split_into(storage: [][]const u8, source: []const u8, separator: []const u8) SplitResult
```

[Source](../../compiler/std/strings/strings.dyn#L392)

Allocates only the slice table in arena. Elements borrow source bytes; keep BOTH alive.
Arena rewind/reset/release expires the table. This is not a deep copy of source.

```dyn
pub fn split(arena: *memory.Arena, source: []const u8, separator: []const u8) SplitResult
```

[Source](../../compiler/std/strings/strings.dyn#L406)

Caller storage must not overlap source. Capacity failure leaves it unchanged.

```dyn
pub fn replace(destination: []u8, source: []const u8, needle: []const u8, replacement: []const u8) Result
```

[Source](../../compiler/std/strings/strings.dyn#L439)

Byte wildcard matching: * matches any sequence, ? one byte, backslash escapes.
Uses constant memory and no recursive backtracking.

```dyn
pub fn glob_match(pattern: []const u8, text: []const u8) bool
```
