# Metaprogamming

Dyn provides several ways to metaprogram, similar to how zig does it.

## Types As Values

Dyn supports using `type` as a valid, well, type for variables and parameters in functions, this means you can pass types (like u32, f32, arrays, named types) as arguments into functions, as values for structs, or as variables too.

```dyn
my_id := i32
some_fn := (t: type) type { // and functions can return types too
    return []t // returns array of type t
}
main := () {
    inner_struct := struct {
        id: my_id, // i32
        other_things: some_fn(my_id), // []id -> []i32
    }
    thing := inner_struct{id: 1, other_things: [1,2,3]}
}
```

## Generics

Dyn does not support generics in traditional sense, rather dyn supports ability to create types with "generic" parameters through function calls and using type parameters. Below is a simple example:

```dyn
List := (t: type) type => struct {
    items: []t
}

HashMap := (k, v: type) type => struct {} // could have multiple types

main := () {
    IntList := List(i32) // IntList now a struct that can be initialized
    IntMap := HashMap(i32, i32)
    ints := IntList{ items: [1,2,3,4] }
    intMap := IntMap{}
}
```

## Compile time

Dyn also allows you to run code during compilation, this lets you do conditional compilation, iterate out loops of code, and do tasks before runtime to prevent extra calculations, this is triggered with `comp` keyword.

```dyn
use_f64 := true // variable known at compile time
calc_pi := () comp if(use_f64) f64 else f32 { // if is checked at comptime
    // return some amount of pi with calculations
}

main := () {
    pi := comp calc_pi() // run as a comp expression, will already be done since
                         // function already has compile time stuff in it though
}
```

### How `comp` Works

`comp` keyword has three main uses:

**1. As a function modifier**
When placed before function body, marks that function is evaluated at compile time:

```dyn
calc_pi := () comp f32 {
    // complex calculation - runs during compilation
    return 3.14159265359
}

main := () {
    pi := calc_pi() // No runtime cost, replaced with constant
}
```

**2. As an expression modifier**
Forces evaluation at compile time:

```dyn
main := () {
    // This expression is computed during compilation
    value := comp (2 + 3) * 4  // becomes 20 at compile time

    // Type-dependent calculations
    size := comp $size_of(i32)  // constant 4
}
```

**3. For conditional compilation**
Branches that are provably false at compile time are completely removed:

```dyn
debug_mode := false

main := () {
    if comp debug_mode {
        // This entire block is eliminated in release builds
        $println("Debug info")
    }
}
```

### Compile-time Type Constraints

You can specify that a parameter must be known at compile time:

```dyn
Vector := (T: type comp) type => struct {
    data: []T
    len: u64
}
```

`comp` after `type` means `T` must be a compile-time known type, enabling better code generation.

### Compile-Time Loops

When loops are executed at compile time, they unroll:

```dyn
create_array := () comp [5]i32 {
    arr := [5]i32{}
    for 0..5: |i| {
        arr[i] = i * 2
    }
    return arr
}

// Becomes: [0, 2, 4, 6, 8] as a compile-time constant
```

A benefit of comp is that you can mark a type parameter, meaning type it uses needs to be known at compile time, which just adds safety and help with code generation.

### Inlining

You can also inline both functions and for loops in dyn as well and they will get unrolled during compilation. There are a few caveats though:

- values only apply to iterable expressions
- values need to be known at compile time, which can also be an expression computed at compile time

In case of functions, in order to have it inlined, specify that when creating function.

```dyn
fn_inlined := inline () {
    // anything in here will be printed out wherever function is used
    x := y
}

main := () {
    fn_inlined()
    /*
        gets placed here:
        x := y
    */
}
```

For for loops, same kind of thing happens, but a little different:

```dyn
io := use "std/io" // example, not final std lib
main := () {
    inline for 0..10: |i| io.print("{}", i)
    // becomes
    // io.print("{}", 0)
    // io.print("{}", 1)
    // io.print("{}", 2)
    // io.print("{}", 3)
    // io.print("{}", 4)
    // io.print("{}", 5)
    // io.print("{}", 6)
    // io.print("{}", 7)
    // io.print("{}", 8)
    // io.print("{}", 9)
}
```
