# Type Coercion

Dyn allows coercing types in a couple ways.

## Standard Coercion

This is most common, and usually is just when you provide a type to another place that expects a different type. This is valid when:

- Going from int to float types

```dyn
float_math := (x: f32) f32 => x * 2

main := () {
    a: i32 = 12
    b := float_math(a)
    c: u32 = 12
    d := float_math(c)
}
```

- Going from unsigned to signed

```dyn
int_math := (x: i32) i32 => x * -2
main := () {
    a: u32 = 12
    b := int_math(a)
}
```

- Going from smaller bit widths to larger bit widths

```dyn
int_math := (x: u64) u64 => x * -2
float_math := (x: f64) f64 => x * 2
main := () {
    a: u32 = 12
    b: f32 = 12.1
    c := int_math(a)
    d := float_math(b)
}
```

## Casting

Explicitly casting something requires use of a builtin function, something like `$as()` or `$shrink()`.

## Grouped

This is type of casting that gets applied to things like ifs, matches and blocks that give values (especially of different types), this is particularly useful when dealing with optional values and like:

```dyn
main := () {
    // Ifs with different numeric types coerce to largest common type
    x := if true 1 else 2.5  // x is comp_float (largest of i32 and f64)

    // Optional values can be coerced from any type to optional version
    y := if true 1 else null  // y is ?comp_int
    z := if true 1.5 else null  // z is ?comp_float

    // Blocks returning values follow same rules
    w := {
        if true break 1
        break 2.5  // coerces to f64
    }
}
```

Coercion follows these rules:

- Numeric types coerce to largest type in set
- Any type can coerce to its optional version (`T` → `?T`)
- If all branches return `null`, result is `?T` where T is inferred from context
