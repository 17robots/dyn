# Changelog

Upgrade notes for Dyn code and the agents that write it. Newest release first.
Preview 9 and 10 are backward compatible: code that built on preview 8 still
builds. The one tooling exception is `dyn fmt --check`, which applies stricter
layout rules from preview 9 on. The other migrations below are cleanups, not
required fixes.

## Upgrading

Pin the new version and its checksums from [`mise.example.toml`](mise.example.toml),
run `mise install`, and confirm with `dyn version`. Restart editor language
servers so they pick up the new `dyn`.

## 0.1.0-preview.10

### Range for-in loops

`for` accepts an integer range after `in`:

```dyn
for i in 0..count {    // 0, 1, ..., count - 1
  _ = values[i]
}
for i in 1..=count {   // 1, 2, ..., count
  _ = i
}
```

- Both bounds share one integer type. A literal bound adapts to the other bound,
  so `0..count` has `count`'s type and `0..#len(values)` is `usize`.
- When both bounds are literals, the binding is `usize`, or `isize` if a bound
  is negative. `for i in 0..3 { values[i] }` indexes directly.
- Bounds evaluate once, first bound first. `5..2` runs no iterations.
- The binding is a copy. Assigning it inside the body does not change the
  iteration. `for *i in 0..n` is an error.
- `..=` may end at the type's maximum. `for b in 250..=top` with `top: u8 = 255`
  runs 6 times without overflow.
- Mixed bound types such as `u8..u32` are an error: "range bounds require the
  same integer type".

**Migration.** Replace manual counter loops:

```dyn
i: usize = 0
for i < count {
  work(i)
  i += 1
}
```

with:

```dyn
for i in 0..count {
  work(i)
}
```

Convert only when all of these hold, or behavior can change:

1. `i += 1` is the last statement of the body.
2. The body never assigns `i` or takes `&i`.
3. The body has no `continue`. In a manual loop `continue` skips the
   increment; in a range loop it advances to the next value.
4. `i` is not used after the loop. A range binding exists only inside the loop.
5. The body cannot change the end bound. The manual loop rereads `count` on
   every iteration; the range reads it once. Keep manual loops whose end is a
   field reached through a pointer, a global, or a local whose address is taken.

Loops that step by more than one, count down, or change the counter inside the
body stay as condition loops.

### Names are reusable after their scope ends

A local declared in a block or loop no longer reserves its name for the rest of
the function. Consecutive loops can each use `i` or `value`, and a name can be
declared again after an earlier block ends:

```dyn
for value in first {
  _ = value
}
for value in second {
  _ = value
}
```

Shadowing is still forbidden: a local cannot reuse the name of a visible local
or parameter, including an enclosing loop's binding.

**Migration.** Names such as `i2`, `index_b`, or `value_2` that only avoided the
old rule can go back to the natural name. Previously, redeclaring a name after
its block also reported a spurious `unknown name` at the redeclaration; that is
gone.

### Standard library

122 std counter loops now use range loops. No public API changed.

## 0.1.0-preview.9

### `dyn fmt` works on real modules and enforces layout

`dyn fmt DIR` used to run full semantic checks without loading imports, so any
module with `use` failed with "unknown name" errors. It now only requires every
file to parse, validates all files before writing any, and reports the first
syntax error per file.

`dyn fmt` and editor formatting now apply:

- One statement per line. `if ready { return }` becomes three lines, and
  `x := 1 y := 2` is split.
- One space after every comma: `add(4, 2)`, `[1, 2, 3]`. No space is added
  before a closing bracket or at a line end.
- LF line endings, no trailing spaces or tabs, and a final newline.

The formatter only inserts or removes whitespace between tokens, so it cannot
change behavior. Running it twice changes nothing.

**Migration.** `dyn fmt --check` now fails on code that passed on preview 8.
Run `dyn fmt DIR` for each module directory and commit the result
separately from other changes. Add `dyn fmt --check DIR` to CI. Write new code
in this layout: two-space indent, one statement per line, a space after commas,
`snake_case` functions and locals, and `PascalCase` types, enum variants, and
constants.

### Editor formatting

LSP formatting returns only the changed lines, returns no edits for an already
formatted or malformed document, and answers requests for unknown documents
with `null` instead of leaving the client waiting.

### Editor completion

Top-level completion no longer analyzes the whole project. A completion request
queued behind edits is answered before project-wide diagnostics run.

### Building the compiler

These affect only people building `dyn` from source:

- `tools/build.py` compiles one object per source file in parallel. Set the
  worker count with `JOBS=n` or `--jobs n`.
- Linker flags in `CPPFLAGS` (`-L`, `-l`, `-Wl,`) are passed to the link step
  only.
- The WASI runtime objects use the `wasm32-wasip1` target.

### Standard library

std was reformatted with the new layout rules. No public API changed.
