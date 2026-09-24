# std/text/regex

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-depth/main.dyn](../../tests/sdk-depth/main.dyn)
- [tests/sdk-hardening/main.dyn](../../tests/sdk-hardening/main.dyn)
- [tests/stdlib-depth/main.dyn](../../tests/stdlib-depth/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/text/regex/regex.dyn

[Source](../../compiler/std/text/regex/regex.dyn#L1)

```dyn
pub struct Match { start: usize, end: usize, ok: bool }
```

[Source](../../compiler/std/text/regex/regex.dyn#L5)

Caller-owned compiled form. `compile` writes only into storage/workspace.
Syntax identifies malformed patterns; Capacity asks caller for larger buffers.

```dyn
pub enum CompileError { None, Syntax, Capacity, Depth }
```

[Source](../../compiler/std/text/regex/regex.dyn#L6)

```dyn
pub struct Instruction { op: u8, byte: u8, x: usize, y: usize, z: usize }
```

[Source](../../compiler/std/text/regex/regex.dyn#L7)

```dyn
pub struct Program { pattern: []const u8, code: []Instruction, start: usize, groups: usize, error: CompileError, ok: bool }
```

[Source](../../compiler/std/text/regex/regex.dyn#L187)

Compiles into caller storage. workspace holds postfix tokens; scratch holds two
usizes per fragment. Required sizes are pattern-dependent and failure is clean.
Program borrows pattern and storage. Keep both alive and unchanged while using it.

```dyn
pub fn compile(pattern: []const u8, storage: []Instruction, workspace: []Instruction, scratch: []usize) Program
```

[Source](../../compiler/std/text/regex/regex.dyn#L285)

Finds with a compiled program. Capture 0 corresponds to the first '(' group.

```dyn
pub fn find_compiled(program: Program, text: []const u8, captures: []Match) Match
```

[Source](../../compiler/std/text/regex/regex.dyn#L396)

Top-level alternation; escaped bars and bars in byte classes are literals.

```dyn
pub fn find(pattern: []const u8, text: []const u8) Match
```

[Source](../../compiler/std/text/regex/regex.dyn#L419)

```dyn
pub struct Iterator { pattern: []const u8, text: []const u8, offset: usize, done: bool }
```

[Source](../../compiler/std/text/regex/regex.dyn#L420)

```dyn
pub fn iterator(pattern: []const u8, text: []const u8) Iterator
```

[Source](../../compiler/std/text/regex/regex.dyn#L421)

```dyn
pub fn next(state: *Iterator) Match
```

[Source](../../compiler/std/text/regex/regex.dyn#L431)

```dyn
pub fn matches(pattern: []const u8, text: []const u8) bool
```
