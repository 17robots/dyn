# std/text/template

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-template/main.dyn](../../tests/sdk-template/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/std/text/template/template.dyn

[Source](../../compiler/std/text/template/template.dyn#L5)

```dyn
pub enum ErrorKind { None, Syntax, OutOfMemory, Io }
```

[Source](../../compiler/std/text/template/template.dyn#L7)

```dyn
pub struct Template { source: []const u8 }
```

[Source](../../compiler/std/text/template/template.dyn#L8)

```dyn
pub struct Field { name: []const u8, value: []const u8 }
```

[Source](../../compiler/std/text/template/template.dyn#L9)

```dyn
pub struct ParseResult { template: Template, error: ErrorKind, error_offset: usize, ok: bool }
```

[Source](../../compiler/std/text/template/template.dyn#L10)

```dyn
pub struct RenderResult { error: ErrorKind, system_error: isize, ok: bool }
```

[Source](../../compiler/std/text/template/template.dyn#L34)

```dyn
pub fn parse(arena: *memory.Arena, source: []const u8) ParseResult
```

[Source](../../compiler/std/text/template/template.dyn#L72)

```dyn
pub fn render(destination: stream.Writer, template: *const Template, fields: []const Field) RenderResult
```

[Source](../../compiler/std/text/template/template.dyn#L77)

Field rendering seam shared by plain-text and HTML templates. Literal text is unchanged.

```dyn
pub fn render_with(destination: stream.Writer, template: *const Template, fields: []const Field,
  render_field: *fn(stream.Writer, []const u8) RenderResult) RenderResult
```
