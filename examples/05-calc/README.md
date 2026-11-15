# 05 · calc

A calculator that reads one expression per line, with variables and a few
functions.

```sh
dyn run examples/05-calc < examples/05-calc/input.txt
dyn run examples/05-calc     # then type: let r = 2, pi * r ^ 2
```

Errors point at the problem:

```
> 2 * (3 + 4
            ^ expected )
```

## What it teaches

- **Tagged enums.** A variant can carry one value: `Token.Number: f64`,
  `Token.Name: []const u8`. `case` binds the payload,
  `Token.Number value => {...}`, and must handle every variant, so adding one
  to `Expr` makes every unfinished `case` fail to compile.
- **Trees in an arena.** `Expr.Binary` carries an `Operation` whose `left`
  and `right` are `*Expr` nodes pushed onto the frame arena. The whole tree
  disappears when `main` resets the frame after the line; nothing walks the
  tree to free it.
- **Recursive descent.** `sum` calls `product` calls `unary` calls `power`
  calls `atom`, which calls `sum` again inside parentheses. Each grammar rule
  in `syntax.dyn` is one function.
- **Sticky failure.** The parser keeps its first failure. After that, every
  step returns an `Invalid` node and changes nothing, so the grammar
  functions read straight through without checking after each call, and
  `parse_line` checks once at the end.
- **A result type of your own.** Evaluation can fail in ways a parser
  cannot (unknown names, division by zero), so `eval.dyn` defines
  `Value { number, problem, offset }`. The zero `Problem` means success.
- **Maps.** `map.Map([]const u8, f64)` holds the variables. `map.get` returns
  a pointer, or `nil` when the key is absent. Keys must outlive the map, so a
  new variable's name is copied into the permanent arena.
- **Generic functions from std.** `math.sqrt`, `math.pow` and `math.min`
  work on any numeric type; the type is inferred from the arguments.

## Exercises

1. Add comparison operators that give 1 or 0: `<`, `>`, `==`.
2. Add a two-argument function, `max(a, b)`. What has to change in `Expr`?
3. Print `x = ...` for every variable when the input says `vars`. A
   `map.walk` visits every entry.
