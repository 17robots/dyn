# Math

Dyn supports integer and float math. Overflow and underflow checking behavior depends on the optimization level.

## Overflow

Overflow occurs when the result from a math operation is a value higher than the maximum of the integer or float being used.

**In Debug/Checked modes:** Overflow/underflow is checked and will cause a runtime error.

**In Release mode:** Overflow/underflow wraps around (two's complement behavior) for performance.

```dyn
main := () {
    a: u8 = 255 // max size
    b: u8 = 1
    c: u8 = a + b // overflows - error in debug, wraps in release

    x: i8 = 127 // max signed
    y: i8 = 1
    z: i8 = x + y // overflows - error in debug, wraps in release
}
```

Compile with:

- `dyn build --debug` or `dyn build -g` - overflow checking enabled (default for development)
- `dyn build --release` or `dyn build -O2` - overflow checking disabled, wraps for performance

## Underflow

Underflow occurs when the result from a math operation is a value lower than the minimum of the integer or float being used.

```dyn
main := () {
    a: u8 = 0 // min size
    b: u8 = 1
    c: u8 = a - b // underflows - error in debug, wraps in release

    x: i8 = -128 // min signed
    y: i8 = 1
    z: i8 = x - y // underflows - error in debug, wraps in release
}
```

## Explicit Overflow Control

To explicitly allow wrapping behavior regardless of optimization level, use `$wrapping`:

```dyn
main := () {
    a: u8 = 255
    b: u8 = 1
    c: u8 = $wrapping(a + b) // always wraps, even in debug
}
```

To enforce checking even in release mode, use `$checked`:

```dyn
main := () {
    a: u8 = 255
    b: u8 = 1
    c: u8 = $checked(a + b) // always checks, even in release
}
```
