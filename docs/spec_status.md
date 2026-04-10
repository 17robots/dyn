# Spec Status Against `spec/`

This note compares the current compiler behavior to the newer spec in `spec/main.md` and `spec/appendices.md`.

Checked on 2026-04-09 with:
- `cargo test -q`
- targeted `cargo run -- parse ... --ast`
- targeted `cargo run -- analyze ...`

The current test suite passes, but there are still meaningful mismatches.

## Summary

There are three buckets:

1. The compiler is behind the new spec in a few real frontend rules.
2. The compiler still implements some older/extra language surface that the new spec does not currently document.
3. The new spec itself appears to have a few omissions relative to both the old `language_spec.md` and the compiler.

## Compiler Behind The New Spec

### 1. No-shadowing is not enforced locally

The spec says names may not be rebound in the current scope or any enclosing lexical scope.

Current behavior:
- local names are inserted with no duplicate/shadow check in [src/compiler/sema/mod.rs](/home/mdray/17robots/dyn/src/compiler/sema/mod.rs#L321)
- block bindings, destructures, and params all use that same insert-only path in [src/compiler/sema/mod.rs](/home/mdray/17robots/dyn/src/compiler/sema/mod.rs#L444)

Observed repro:

```dyn
module main
main := () {
  x := 1
  { x := 2 }
}
```

`cargo run -- analyze` accepts this today.

### 2. `if` used as an expression does not require `else`

The spec requires all branches for expression-form `if`.

Current behavior:
- parser makes `else` optional in [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L969)
- type inference accepts the form and just infers from the then-branch path in [src/compiler/sema/infer.rs](/home/mdray/17robots/dyn/src/compiler/sema/infer.rs#L218)

Observed repro:

```dyn
module main
x := if true 1
main := () {}
```

This also analyzes cleanly today.

### 3. Typed struct literal field shorthand is missing

The new spec allows:

```dyn
Point{ x, y }
```

Current behavior:
- struct literal parsing requires `name: expr` for every field in [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L2006)

Observed repro:

```dyn
module main
main := () {
  p := Point{ x }
}
Point := struct { x: i32 }
```

This fails in the parser with `expected ':' in struct literal field`.

### 4. `*mut T` and `[]mut T` parameter types are not parsed correctly

The new spec explicitly allows these forms in parameter positions.

Current behavior:
- generic type parsing only understands plain `*T` and `[]T` in [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L1571)
- `mut` is then consumed as an identifier, which corrupts the parameter list

Observed repros:

```dyn
module main
f := (p: *mut i32) {}
```

```dyn
module main
f := (p: []mut u8) {}
```

Both misparse today and emit `expected ',' between function parameters`.

### 5. Top-level executable statements are skipped, not diagnosed

The spec says only declarations are valid at top level.

Current behavior:
- parse only recognizes top-level declarations via [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L37) and [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L2361)
- anything else is advanced past by [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L2412)

Observed repro:

```dyn
module main
x := 1
x + 2
main := () {}
```

The `x + 2` line is silently dropped from the AST instead of producing an error.

### 6. Named-argument ordering rule is not enforced

Appendix B recommends the v0.1 rule that after the first named argument, all following arguments must be named.

Current behavior:
- call checking validates unknown names, duplicates, arity, defaults, and types in [src/compiler/sema/infer.rs](/home/mdray/17robots/dyn/src/compiler/sema/infer.rs#L4094)
- it does not reject a positional argument after a named one

Observed repro:

```dyn
module main
main := () {
  add := (x: i32, y: i32) i32 => x + y
  add(y: 1, 2)
}
```

This analyzes cleanly today.

## Compiler Ahead Of Or Divergent From The New Spec

These are not necessarily bugs. Some look like legacy features or spec omissions.

### 1. `packed struct` is still a language keyword and parse path

- lexer still reserves `packed` in [src/compiler/lexer.rs](/home/mdray/17robots/dyn/src/compiler/lexer.rs#L870)
- parser still accepts it in expressions and types in [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L377) and [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L1619)

The new spec keyword list in `spec/main.md` does not include `packed`.

### 2. The compiler implements `extern` declarations, but `spec/` does not fully spell them out

- parser supports binding-form extern declarations in [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L158) and [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L1206)
- HIR/backend also carry externs through lowering and codegen

`extern` is listed as a keyword in `spec/main.md`, but the new grammar in `spec/appendices.md` does not currently define the declaration form.

### 3. The compiler supports `fn(...) T` type syntax, but the new type grammar omits it

- parser accepts function type expressions in [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L1651)
- type checking models function types in [src/compiler/sema/mod.rs](/home/mdray/17robots/dyn/src/compiler/sema/mod.rs#L2308)

This looks more like a spec gap than an implementation problem.

### 4. The compiler supports enum reprs and enum body members

- parser accepts `enum(u8)` reprs in [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L1789)
- parser also accepts `name := expr`-style enum members in [src/compiler/parser.rs](/home/mdray/17robots/dyn/src/compiler/parser.rs#L1815)

The new appendix grammar only documents simple variants with optional payloads.

### 5. Module mapping is stricter than the new spec currently promises

The new spec says filesystem-to-module mapping is implementation-defined for v0.1.

Current behavior is stricter and user-visible:
- subdirectory modules must match file stem or directory name in [src/compiler/module_resolver.rs](/home/mdray/17robots/dyn/src/compiler/module_resolver.rs#L389)
- mismatches produce an error in [src/compiler/module_resolver.rs](/home/mdray/17robots/dyn/src/compiler/module_resolver.rs#L433)

This is fine as an implementation choice, but it is stricter than the spec text.

## Recommendation

I would treat the deltas in this order:

1. Fix true spec violations first:
   - no-shadowing
   - expression-form `if` requiring `else`
   - typed struct literal shorthand
   - `*mut` / `[]mut` parameter parsing
   - top-level statement diagnostics

2. Decide which legacy features are still intended:
   - `packed`
   - enum reprs
   - enum body members
   - `extern`
   - `fn` type syntax

3. Then either:
   - update `spec/` to keep those features, or
   - remove them from the compiler and add regression tests.

## My Read

The compiler is already closer to the older `language_spec.md` than to the newer `spec/` draft in a few places. The important architectural point is that most gaps are parser/sema-policy issues, not backend blockers. This is good news: the main work is tightening frontend behavior and deciding whether `spec/` is intentionally narrowing the language or just incomplete.
