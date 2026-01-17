# Functions

Functions in dyn operate same as other variables, they are first-class citizens in dyn.

## Function Types

Function types are written as `fn(param_types) return_type` where:

- Parameters are comma-separated types
- Return type follows closing parenthesis
- For void returns, you can omit return type

```dyn
// Function type examples
add_fn := fn(i32, i32) i32  // takes two i32, returns i32
void_fn := fn(i32)           // takes i32, returns void
no_param_fn := fn() i32      // takes nothing, returns i32
```

## Construction

Functions are created as any other variable.

```dyn
add := (x: i32, y: i32) { // void types dont need anything specified
    // print adding x and y
}
```

To give a non void return type, specify return type after ) and before {

```dyn
add2 := (x: i32, y: i32) i32 {
    return x + y
}
```

If you have multiple parameters of same type, you can group them.

```dyn
add3 := (x,y: i32) i32 {
    return x + y
}
```

And if you just have one thing to return, you can use => and expression.

```dyn
add4 := (x,y: i32) i32 => x + y
```

You can also specify default values for a function, including to grouped identifiers.

```dyn
add5 := (x,y: i32 = 0) => x + y
```

### Struct Methods

Structs can have functions as members. These are just normal functions stored in the struct, not special methods.

```
Point := struct {
    x,y: f64,
    new := (x,y: f64) Point => .{ x: x, y: y}
    slope := (a: Point, b: Point) => (b.y - a.y) / (b.x - a.x)
}
```

**Calling as functions:**

```
Point := struct {
    x,y: f64,
    slope := (a: Point, b: Point) => (b.y - a.y) / (b.x - a.x)
}

origin := Point{ x: 0, y: 0 }
other := Point{ x: 1.0, y: 1.0 }

// Call as static function (accessed via struct name)
result := Point.slope(origin, other)
```

**Calling with first parameter as value (similar to methods):**

```
p := Point{ x: 1.0, y: 2.0 }

// When first parameter's type matches the struct, can use dot syntax
slope := p.slope(Point{ x: 0, y: 0 })  // p is passed as first argument

// Equivalent to:
slope := Point.slope(p, Point{ x: 0, y: 0 })
```

## Calling

To call a function in dyn, just use name followed by () with arguments to pass to function provided:

```dyn
main := () {
    add(1, 2)
}
```

Functions that return values can and need to be used as values.

```dyn
main := () {
    x := add2(1, 2)
    y := add2(add3(1, 2), add4(1, add5(1, 2)))
}
```

If a function has default parameters, you dont need to specify them, but since these can appear out of order, you can specify them in call.

```dyn
z := add5(y: 1) // x = 0, y = 1
a := add5(1) // x = 1, y = 0 since it still respects positional stuff
```

You can also call methods on structs with sugared syntax if first argument is type.

```dyn
x := Point{ x: 1, y: 1 }
x.slope(Point.origin) // desugares to Point.slope(x, Point.origin)
```
