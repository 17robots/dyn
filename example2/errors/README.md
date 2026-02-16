# Error Examples

- `lex/main.dyn`: lexer/early parse-oriented tokenization error surface.
- `parse/main.dyn`: parser structure errors.
- `check/main.dyn`: semantic checking errors.
- `type/main.dyn`: focused type-checking mismatches.
- `pointer/main.dyn`: pointer mutability assignment error (`ptr.* = ...` through `*i32`).
- `unwrap/main.dyn`: invalid optional/error unwrap usage (`.?` and `.!` on non-optional/error values).

Run any example:

```bash
zig build run -- check example2/errors/<kind>/main.dyn
```
