# Function types without `*`

The unreleased compiler writes function types without a leading `*`. A
function value is already a code pointer, so the star said nothing.

```dyn
// Before
on_hit: *fn(*Entity, i32) bool
handlers: [4]*fn()

// After
on_hit: fn(*Entity, i32) bool
handlers: [4]fn()
on_hit: fn(target: *Entity, damage: i32) bool // names are optional
```

`*fn(...)` still parses, but it now means a pointer to a function value. Old
code that used it as a function type stops compiling with a type mismatch
(`expected *fn(i32) i32, found fn(i32) i32`) instead of changing meaning
silently. A textual replacement of `*fn(` with `fn(` is a complete migration:
`**fn(` becomes `*fn(`, which keeps a pointer to a function pointer.

Generated bindings follow the same rule; regenerate them with the new
`tools/vendor-bindings.py` and `tools/dyn-bind.py`, or apply the same
replacement. The frontend cache version changes, so analysis cached by an older
compiler is not reused.
