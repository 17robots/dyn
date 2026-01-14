# Math
Dyn supports integer and float math, and will try to check for overflow and
underflow

## Overflow
Overflow occurs when the result (answer) from a math operation is a value higher
than the maximum of the integer or float being used to store the result

```
main := () {
    a: u8 = 255 // max size
    b: u8 = 1
    c: u8 = a + b // overflows and errors

    x: i8 = 255
    y: i8 = 1
    z: i8 = x + y
}
```

## Underflow
Underflow occurs when the result (answer) from a math operation is a value
lower than the minimum of the integer or float being used to store the result

```
main := () {
    a: u8 = 0 // min size
    b: u8 = 1
    c: u8 = a - b // underflows and errors

    x: i8 = -255
    y: i8 = 1
    z: i8 = x - y // underflows and errors
}
```

