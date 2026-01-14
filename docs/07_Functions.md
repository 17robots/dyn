# Functions
Functions in dyn operate the same as other variables, they are first-class
citizens in dyn

## Construction
Functions are created as any other variable

```
add := (x: i32, y: i32) { // void types dont need anything specified
    // print adding x and y
}
```

To give a non void return type, specify the return type after the ) and before
the {

```
add2 := (x: i32, y: i32) i32 {
    return x + y
}
```

If you have multiple parameters of the same type, you can group them

```
add3 := (x,y: i32) i32 {
    return x + y
}
```

And if you just have one thing to return, you can use => and the expression

```
add4 := (x,y: i32) i32 => x + y
```

You can also specify default values for a function, including to grouped
identifiers

```
add5 := (x,y: i32 = 0) => x + y
```

### Struct Methods
Structs can have methods attached to them, this is done by listing a function
type as a member of the struct. This becomes a static function usable from the
struct, accessed as `StructName.function()`, but if the function's first
parameter is the same as the struct type, then it can be sugared to an instance
method rather than a static one

```
Point := struct {
    x,y: f64,
    new := (x,y: f64) Point => .{ x: x, y: y} // static
    slope := (a: Point, b: Point) => (b.y - a.y) / (b.x - a.x) // member fn
}

origin := Point{ x: 0, y: 0 } // static variables not allowed in structs
```

## Calling
To call a function in dyn, just use the name followed by () with the arguments
to pass to the function provided:

```
main := () {
    add(1, 2)
}
```

Functions that return values can and need to be used as values

```
main := () {
    x := add2(1, 2)
    y := add2(add3(1, 2), add4(1, add5(1, 2)))
}
```

If a function has default parameters, you dont need to specify them, but since
these can appear out of order, you can specify them in the call

```
z := add5(y: 1) // x = 0, y = 1
a := add5(1) // x = 1, y = 0 since it still respects positional stuff
```

You can also call the methods on structs with sugared syntax if the first
argument is the type

```
x := Point{ x: 1, y: 1 }
x.slope(Point.origin) // desugares to Point.slope(x, Point.origin)
```

