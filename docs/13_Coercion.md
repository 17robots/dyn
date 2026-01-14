# Type Coercion
Dyn allows coercing types in a couple ways:

## Standard Coercion
This is the most common, and usually is just when you provide a type to another
place that expects a different type. This is valid when:
- Going from int to float types
```
float_math := (x: f32) f32 => x * 2

main := () {
    a: i32 = 12
    b := float_math(a)
    c: u32 = 12
    d := float_math(c)
}
```
- Going from unsigned to signed
```
int_math := (x: i32) i32 => x * -2
main := () {
    a: u32 = 12
    b := int_math(a)
}
```
- Going from smaller bit widths to larger bit widths
```
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
Explicitly casting something requires the use of a builtin function, something
like `$as()` or `$shrink()`

## Grouped
This is the type of casting that gets applied to things like ifs, matches and
blocks that give values (especially of different types), this is particularly
useful when dealing with optional values and the like:
```
```

