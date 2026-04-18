# Dyn Declaration Model Draft

Status: implemented in compiler frontend/AST/HIR. Spec text still being normalized.

Goal: unify declaration-like surface forms under one compiler model.

## Why

Dyn surface already tries to make declaration forms feel same:

```dyn
x := 1
mut x := 1
x: T = 1
Point.origin := Point{ x: 0, y: 0 }
Point.new := (x: i32, y: i32) Point => .{ x, y }
write := extern (fd: i32, ptr: *u8, len: usize) i32 = "dynrt_fd_write"
{ a, b } := pair()
```

Compiler currently splits these too early into separate item kinds. That adds parser branches, sema branches, drift in self-host port, extra special cases.

Intent: represent these as one declaration model, then validate special rules on top.
Current compiler status:
- unified `Declaration` item/stmt model is live
- assignment is stmt-only, not expression AST
- declaration-local `inline` is stored as declaration metadata and lowered later

## Core Model

One top-level/local item kind:

```text
Item::Declaration(Declaration)
```

Suggested shape:

```text
Declaration {
  docs: Vec<DocComment>
  visibility: Visibility
  modifiers: DeclModifiers
  target: DeclTarget
  annotation: Option<TypeExpr>
  value: Expr
  span: SourceSpan
}
```

Suggested modifier split:

```text
DeclModifiers {
  mutable: bool
  inline: bool
  linkage: Linkage
}

Linkage =
  Normal
  Extern { link_name: Option<String> }
```

Suggested target split:

```text
DeclTarget =
  Name(Ident)
  Associated { base: AssocBase, member: Ident }
  Destructure(Vec<DestructureName>)

AssocBase =
  Ident
```

Notes:
- `Associated` covers both methods and associated values/constants.
- `Point.origin := Point{ ... }` and `Point.new := (...) ...` same target shape.
- Start with `AssocBase = Ident`. Widen later only if language truly needs more.
- Keep `value: Expr` for all forms. `extern` stays declaration metadata, not separate expression/node family.

## Surface Mapping

### Plain binding

```dyn
x := 1
```

```text
Declaration {
  modifiers: { mutable: false, inline: false, linkage: Normal }
  target: Name("x")
  annotation: None
  value: 1
}
```

### Typed binding

```dyn
x: T = 1
```

Same as above, with `annotation = Some(T)`.

### Mutable binding

```dyn
mut x := 1
```

Same as plain binding, with `modifiers.mutable = true`.

### Associated declaration

```dyn
Point.origin := Point{ x: 0, y: 0 }
Point.new := (x: i32, y: i32) Point => .{ x, y }
```

```text
target = Associated { base: Point, member: origin/new }
```

No separate “type binding” node needed.

### Extern declaration

```dyn
write := extern (fd: i32, ptr: *u8, len: usize) i32 = "dynrt_fd_write"
```

Suggested parsed shape:

```text
Declaration {
  modifiers.linkage = Extern { link_name: Some("dynrt_fd_write") }
  target = Name("write")
  annotation = None
  value = Expr::Fn(FnExpr { ... body: missing/extern body marker? })
}
```

Important compiler choice:
- either keep `value` as normal `FnExpr` plus `linkage = Extern`
- or allow small `ExprKind::ExternFnSig` helper expression used only before lowering

Preferred direction: keep extern as declaration property. Avoid separate `Item::Extern`.

### Inline function declaration

```dyn
id := inline (x: i32) i32 => x
```

```text
Declaration {
  modifiers.inline = true
  target = Name("id")
  value = Expr::Fn(...)
}
```

Validation rule: `inline` only legal when `value` is function expression.

### Destructure declaration

```dyn
{ a, b } := pair()
```

```text
target = Destructure([a, b])
```

No separate `Item::Destructure` needed.

## Validation Rules

These should live after parse, not in AST shape.

### General

- All declarations require initializer/value.
- `pub` only valid at top level.
- No shadowing rules apply to names introduced by declaration target.
- Associated declarations do not introduce lexical name `member`; they register member on associated base.

### `mut`

- `mut` only valid for `DeclTarget::Name` and destructure items marked mutable.
- `mut` invalid for associated declarations.

### `inline`

- `inline` only legal on declarations whose value is function expression.
- `inline` appears in declaration modifier position only:

```dyn
f := inline (x: i32) i32 => x
```

- Reject postfix/in-expression form like:

```dyn
f := () i32 => inline 9
```

### `extern`

- `extern` only legal on name target, not associated/destructure target.
- `extern` only legal when value is function signature form accepted by frontend.
- `extern` declarations cannot be `mut`.
- `extern` carries optional link name.

### Associated declarations

- `Associated` target allowed only at top level.
- Associated declaration may bind value, function, type, constant-like expression.
- Example valid forms:

```dyn
Point.origin := Point{}
Point.zero: Point = .{ x: 0, y: 0 }
Point.new := (x: i32, y: i32) Point => .{ x, y }
```

### Destructure

- Destructure declarations allowed where local declarations are allowed.
- Top-level destructure remains invalid unless language explicitly changes.
- Annotation on whole destructure should be unsupported at first unless semantics clear.

## Parser Direction

Prefer one parser entry for declaration syntax:

```text
parse_declaration(context)
```

Context decides which targets/modifiers legal:

```text
DeclContext =
  TopLevel
  Local
```

Suggested flow:

1. Parse docs / visibility if top-level
2. Parse declaration modifiers (`mut`, maybe `inline` in decl position)
3. Parse target:
   - name
   - associated target
   - destructure target
4. Parse annotation or `:=`
5. Parse value
6. Run context-sensitive validation

Do not branch into separate parse paths for:
- plain binding
- associated binding
- extern binding
- destructure binding

Those become same parse family.

## AST Transition Plan

Do not rewrite whole compiler in one shot.

### Stage 1

- Add new `Declaration` model in AST.
- Parser emits unified declaration.
- Add temporary lowering from unified declaration into old item variants.

### Stage 2

- Move sema/HIR to consume unified declaration directly.
- Delete old split item variants:
  - `Binding`
  - `Destructure`
  - `Extern`
  - `TypeBinding`

### Stage 3

- Update self-host compiler AST first.
- Keep Rust AST and Dyn AST field names identical.
- Add regression tests for each declaration surface form.

## Open Questions

### 1. Extern value representation

Need exact internal form for extern signature:
- declaration metadata + normal fn expr
- declaration metadata + dedicated extern-signature expr

Least conceptual weight: declaration metadata + fn-like signature node.

### 2. Whole-pattern mutability

Keep only item-level mutability:

```dyn
{ mut a, b } := value
```

Do not support:

```dyn
mut { a, b } := value
```

Recommended: keep current per-name mutability only.

### 3. Associated base grammar

For now:

```text
AssocBase := Ident
```

Do not widen to arbitrary type expressions until needed.

### 4. Typed associated declarations

Allow:

```dyn
Point.origin: Point = Point{}
```

Recommended: yes. Fits unified declaration model naturally.

## Immediate Follow-Up Work

1. Update Rust AST to introduce `Declaration`, `DeclTarget`, `DeclModifiers`, `Linkage`.
2. Lower old parser branches into unified parse path.
3. Add tests:
   - plain declaration
   - typed declaration
   - associated value declaration
   - associated function declaration
   - extern declaration
   - inline declaration
   - destructure declaration
4. Mirror same AST exactly in `compiler-dyn/ast.dyn`.
