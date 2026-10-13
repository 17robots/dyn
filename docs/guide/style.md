# Dyn style

`dyn fmt` and editor formatting apply the layout rules below. Run `dyn fmt --check DIR` in CI.
The naming rules are conventions; the formatter does not rename anything.

## Layout (enforced by `dyn fmt`)

- One statement per line. A block's statements never share a line with `{`, `}`, or each other,
  so `if ready { return }` becomes three lines.
- One space after every comma: `add(4, 2)`, `[1, 2, 3]`. A comma before a closing bracket or at a
  line end gets no space.
- LF line endings, no trailing spaces or tabs, and a final newline.

## Layout (by convention)

- Indent with two spaces per block level. Never use tabs.
- Put spaces around binary operators and `:=`: `total := a + b`.
- Keep `} else {` on one line.
- Empty blocks stay on one line: `fn noop() {}`.

```dyn
fn clamp(value: i32, low: i32, high: i32) i32 {
  if value < low {
    return low
  } else if value > high {
    return high
  }
  return value
}
```

## Naming

- Functions, locals, parameters, fields, and module paths: `snake_case`.
- Structs, enums, enum variants, and constants: `PascalCase`.
- Import aliases: short `snake_case` module names.

For idioms beyond layout, see [idiomatic Dyn](idiomatic-dyn.md).
