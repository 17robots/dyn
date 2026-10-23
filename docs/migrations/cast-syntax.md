# Delimited cast syntax

The unreleased compiler replaces prefix casts with two-argument forms. This is
an immediate source break; older released compilers still require the old form.
Upgrade the compiler, SDK sources, and editor grammar together.

```dyn
// Before
wide := #cast(i64) value
bits := #bitcast(u32) number
view := (#cast(*u8) memory)[..count]

// After
wide := #cast(i64, value)
bits := #bitcast(u32, number)
view := #cast(*u8, memory)[..count]
```

Preserve the original operand boundary. The old `#cast(i64) a + b` becomes
`#cast(i64, a) + b`, not `#cast(i64, a + b)`. A nested prefix cast becomes
`#cast(i64, #cast(i32, value))`. Preserve comments and parentheses within operands.
Do not migrate source using a regular expression that guesses where expressions end.

Numeric, pointer, enum, and bit-reinterpretation rules do not change. Operands
are evaluated once. Old forms produce an explicit migration diagnostic.

For rollback, use the previous source revision with its matching compiler and SDK.
Do not mix the new SDK source with an older compiler. The frontend cache version
changes so serialized analysis from the old grammar is not reused.
