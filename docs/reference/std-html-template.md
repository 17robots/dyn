# std/html/template

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

## Source: compiler/std/html/template/template.dyn

[Source](../../compiler/std/html/template/template.dyn#L5)

```dyn
pub type ErrorKind = core.ErrorKind
```

[Source](../../compiler/std/html/template/template.dyn#L6)

```dyn
pub type Template = core.Template
```

[Source](../../compiler/std/html/template/template.dyn#L7)

```dyn
pub type Field = core.Field
```

[Source](../../compiler/std/html/template/template.dyn#L8)

```dyn
pub type ParseResult = core.ParseResult
```

[Source](../../compiler/std/html/template/template.dyn#L9)

```dyn
pub type RenderResult = core.RenderResult
```

[Source](../../compiler/std/html/template/template.dyn#L11)

```dyn
pub fn parse(arena: *memory.Arena, source: []const u8) ParseResult
```

[Source](../../compiler/std/html/template/template.dyn#L44)

Escapes text and quoted attribute values. Not a JS/CSS/URL-context sanitizer.

```dyn
pub fn render(destination: stream.Writer, template: *const Template, fields: []const Field) RenderResult
```
