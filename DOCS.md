# Getting Started

TODO:
- redo methods on structs to allow for passing inlined structs with
  methods on them to be called when passed and redefine a method to be any
  function typed member on a struct
- finish pointers

# Syntax
## Comments
`// This is a comment`

```
/* Block
   comment
   here
   multiple
   lines */
```

## Keywords
Dyn has the following keywords:

```
break continue defer enum fn for if match mut or struct use
```

## Terminators
Dyn supports the following terminators for statements: `'\n'`, `';'` (required
if you want to separate multiple statements on one line), `'\0'`

## Operator Precedence
|Prec|Operator|Description|Associates|
|:-:|:-:|:-:|:-:|
|1|() [] .|Grouping, Subscript, Method Call|Left|
|2|- ! ~|Negate, Not, Complement|Right|
|3|* / %|Multiply, Divide, Modulo|Left|
|4|+ -|Add, Subtract|Left|
|5|.. ..=|Range, Inclusive Range|Left|
|6|<< >>|Shift Left, Shift Right|Left|
|7|&|Bitwise And|Left|
|8|^|Bitwise Xor|Left|
|9|\||Bitwise Or|Left|
|10|< <= > >=|Comparison|Left|
|11|== !=|Equals, Not Equals|Left|
|12|&&|Logical And|Left|
|13|\|\||Logical Or|Left|
|14|=|Assignment, Setter|Right|

# Types
## Simple Types
### Integers
In dyn, integer types are specified as `[u or i][number of bits]` u for unsigned
and i for signed. This grants you more control over how much data gets used in
the program. If the int is signed, the number reserves 1 bit as the sign bit
and the rest is reserved for the number, which means a signed integer will have
a max value of 2^(i-1)-1 where i is the number of bits
But, dyn prefers "accurate representation" over convenience in a couple
places, namely, booleans and characters

#### Booleans
Booleans (true and false) are represented as an unsigned 1 bit int, and is typed
as such. So booleans are just `u1`, and can be set to either 1, 0, true, or
false

#### Characters
Characters are represented as either u8-u32 (1 byte to 4 bytes), with most
English
using just 1 byte, but, just like booleans, the type for a character is just
`u8-32`

#### Literal Representations
In dyn, integer literals can be represented as follows:
As just a number: `1000`
With \_ in them: `1_000`
Binary: `0b1111101000`
Octal: `0o1750`
Hex: `0x3E8`

### Floats
Floats are decimal numbers, and they follow IEEE single `f32` or
double `f64` or quadruple `f128` precision specifications

## Complex Types
### Arrays
Arrays are continuous values of the same type, specified with `[number]typename`,
they are specified as a pointer and a length

#### Slices
Slices are peeks into an array, stored with a pointer and a start, and a length,
specified with `[]typename`

#### Strings
Strings are just arrays or slices of characters, which as above, would be either
`[]u8-32`

### Optional
Optionals represent either a value or nothing, but it's useful for when
something doesnt always need to exist, specified with `?typename`

#### Null
This is the empty value when an optional isnt meant to have anything, specified
with `null`

#### Handling Optionals
You can handle an optional either by unwrapping it and propagating the null with
`.?` or you can use an or block or you can use and if statement (see below)

```
a: ?i32 = null
x := b.? // this propogates the null
y := b or 1 // default value (could also be used for single statement)
z := b or {} // do thing(s)
```

If you want to assign a value to an optional type, you just need to assign it,
there's no optional dereferencing required

```
opt_val: ?i32 = null // you need to specify the type if youre assigning to null
a := opt_val or 1 // type on or needs to match unless void statement, a = 1
opt_val = 2
b := opt_val or 1 // b = 2
```

### Pointer
Pointers are values that hold the address to a value of a given type, they are
stored as the size of the architecture's bit processing (32 for 32 bit systems,
64bits for 64 bit systems) and they can be dereferenced to access the value
being pointed to to access the value. Pointers can be used with both the stack
or the heap

```
a_val: i32 = 4
a_pointing_val := &a_val // returns *i32
```

The address of operator (& prefix) will return either a pointer or a mutable
pointer of the type that youre getting the address of

```
mut a_val: i32 = 4
a_pointing_val := &a_val // returns *mut i32
a_readonly_pointing_val: *i32 = &a_val // *i32 even if the var is mutable
```

In order to use the value that's pointed to by the pointer, you need to
dereference it:

```
mut a_val: i32 = 4
a_pointing_val := &a_val
b := a_pointing_val.*
```

If the pointer is a mutable one (`*mut i32` for example), then the data being
dereferenced can be changed

```
mut a_val: i32 = 4
a_pointing_val := &a_val
a_pointing_val.* = 5
```

In dyn, you can have multiple immutable pointers to a piece of data or you can
have one mutable pointer to a piece of data, it will error otherwise
Pointers also cannot point to nothing unless it's an optional type

Dyn will also try to track pointers to verify that they are used and that there
is always a pointer to allocated data, preventing leaks

### Enums
Enums types are a variant-based, fixed set of values, defined as follows:

```
Week := enum {
    Monday,
    Tuesday,
    Wednesday,
    Thursday,
    Friday,
    Saturday,
    Sunday
}
```

Enums can only be one variant at a time, and are assigned like so:

```

today := Week.Monday // the Week is optional if the variant is inferrable

```

Enum variants can be partnered with a payload type, effectively creating a
tagged union

```
Message := enum {
    Success,
    Warning: []u8,
    ErrorCode: enum { Unauthorized, Invalid } // use enum as literal expression
}
```

To select a variant from an enum with a partner, do the following:

```
variant := .Warning("This is a warning message") // omittable if enum inferred
```

### Structs
Structs are types with blocks of related data pieces. In dyn struct literals are
expressions, defined as follows:

```
AStruct := struct {
    item1: i32,
    item2: i32,
    item3: i32
}
```

Struct members can also be grouped together if the types are similar:

```
AStruct := struct {
    item1, item2, item3: i32,
}
```

And these members can have a default value:

```
AStruct := struct {
    item1, item2, item3: i32 = 0, // can be done for grouped vals
    other: u8 = 'a', // or for single ones
}
```

To instantiate a struct, do the following:

```
x := AStruct{ item1: 1, item2: 2, item3: 3 } // other will still be 'a'
y := AStruct{ other: 'b' } // item1,2,3 = 0 and other is 'b'

// to access a member of a struct:
x.item1
y.other // can be used to get or set
```

# Variables
Variables are names that hold values, all variables have values and a type
telling dyn which kind of values the variable can hold

```
// ways to create variables
x: i32 = 1 // specify the type
y := 1 // infer the type
```

Variables in dyn are immutable by default, so `x = 0` will error unless it is
specified mutable

```
mut z := 1 // can still infer type
z = 0 // can now change without error
```

Variables cannot be set to a value outside of the type assigned to the variable,
even if inferred

```
mut a := 1
a = 1.0 // not allowed
// but since characters and booleans are also integer values, they can be set
a = 'a' // valid, but would be the int val instead of the character value
```

Variables also only exist in the scope they are defined, and cannot be used
outside of that scope

```
a := 1
{
    b := 2 + a // a valid here
}
// c := b + a // b invalid here
```

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

# Control Flow
Dyn offers a couple options for control flow

## For
Only one loop is offered in dyn: the for loop, but it serves as the for and
while loops, which means that a for can accept either a boolean or a list of
iterable expression

### As Iterable
```
main := () {
    for 0..10: |i| {
        // do things with i
    }
}
```

You can also use single statements for a for loop as well:

```
main := () {
    mut sum: i32 = 0
    for 0..10: |i| sum += i
}
```

For loops also support multiple iterable conditions as well:

```
main := () {
    for 0..10, 0..10: |i, j| {}
}
```

All conditions in the for loop need to be the same length. And all conditions
need a capture, or _ to skip it

```
main := () {
    // for 0..10, 0..10: |i| {} - invalid
    for 0..10, 0..10: |i, _| {} // valid
}
```

Ranges aren't the only iterable thing, you can also iterate over arrays as well:

```
main := () {
    x: []i32 = [1,2,3,4,5]
    for x: |i| {
        // do something with the value in x
    }
}
```

By default, captures of values, specifically from arrays, are immutable, so to
change them, you need to mark the capture as default:

```
main := () {
    x: []i32 = [1,2,3,4,5]
    for x: |i| {
        // cannot do i += 1
    }
    for x: |mut i|  i += 1 // now you can because i is marked as mut
}
```

### As Condition
As mentioned above, dyn uses for loops also in place of while loops, so you can
do something like the following:

```
main := () {
    mut x := 1
    for x < 10 x += 1
}
```

Which means that for loops only accept a list of iterables or a boolean
condition, it does not support multiple boolean conditions (unless separated)
by `&&` or `||`

And if you do a for loop with a block and no condition, it acts like an infinite
loop

```
main := () {
    for {
        // do something forever
        break // please make sure to break these
    }
}
```

## If
If statements are branching logic pieces that execute based on the given logic

```
something := 1
if something == 1 {
    // do something
} else {} // else optional for statements
```

You also dont need the {} if it's a single statement/expression

```
mut something := 1
if something == 1 something = 2
```

This also applies to else's too:

```
if something == 1 something = 2 else something = 3
if something == 1 something = 2 else if something == 2 something = 3 else something = 4
```

Ifs can also be used as expressions, doing so this way requires an ending else,
regardless of the amount of else/ifs and each branch needs to evaluate to the
same type

```
x := if something == 1 1 else 0
```

Since ifs as expressions have to evaluate to the same type, blocks used also
need to evaluate to the same type

```
y := if something == 1 { // y evaluates to an int
    // do something else here if you want
    break 1 // int
} else {
    // do something else here too if you want
    break 0 // int
}
```

The only time this changes is with optional types since it's allowed to be a
null or a value

```
z := if something == 1 { // y evaluates to a ?int
    // do something else here if you want
    break 1 // int
} else {
    // do something else here too if you want
    break null
}
```

Ifs can be used for optional types as well, so you can do something like this:

```
maybe := null
if maybe: |v| {
    // do something with v
} else {} // if maybe is null
```

## Match
Match statements give you the ability to execute code based on a series of
patterns and a value that gets matched against them. All values arrays, void
or struct types can be matched against. The patterns you match against need to
be the same type as the value you match.

```
main := () {
    val: i32 = 2
    match val {
        1: {}, // a pattern to match, i32
        2..=10: {}, // another pattern, still seen as i32
        _: {} // the default, covers all other cases
    }
}
```

Another thing to note with patterns being the same type, this also corresponds
to int types of varying bit representations, so if you match on a u8, you can
only match up to a u8's values, and nothing below 0, same with i8 or u/i32, etc

All matches are exhaustive, meaning that every possible case needs to be
covered in the match statement, be it with individually listing the patterns
or with using the _ pattern to catch all others. Patterns also cannot overlap
with each other, which should be achieved since _ is "all other values not
specified"

### Enum Matching
Enums are matched just by listing the variant. If the enum variant has a
partner, then that value can be captured, both immutably and mutably

```
SomeEnum := enum {
    variant1: i32,
    variant2: f32,
    variant3
}

main := () {
    thing := SomeEnum.variant1(i32)
    match thing {
        .variant1: |i| {},
        .variant2: {}, // if you dont want to use the partner, dont include
        .variant3: {}, // no partner so no capture required
        // _: {} - not necessary since all variants covered
    }

    match thing {
        .variant2: |i| {},
        _: {}, // required since variant1 and variant3 not covered, would err
    }

    match thing {
        .variant1: |mut i| { i = 4 }, // change i to be a new value
        _: {},
    }
}
```

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

# Error Handling
Dyn supports errors and handling, and they do this specifically with functions,
you declare that a function can error doing the following

```
some_error_fn := () ! {}
some_returning_error_fn := () f32! {}
```
The ! tells dyn that this function can return back an error type, which gets
inferred if there isnt anything after the !

## Custom Error Types
In dyn, you can use either enums or structs as custom error types. To use them,
list the type after the ! in the function definition

```
SomeError := struct { things: i32, here: i32 }
an_error_fn := () f32!SomeError {} // specify multiple with ,
```

You can also specify several error types as well, separating them with !:

```
SomeError := struct { things: i32, here: i32 }
SomeOtherError := enum {
    A_Thing,
    AnotherThing: f32,
    SubThing: struct {} // specifying a partner as an inline struct
}
an_error_fn := () f32!SomeError,SomeOtherError {} // specify multiple with !
```

## Handling Errors
To manage errors, you can either do `.!` after the call or use the or block with
an optional error capture to handle it, see below:

```
// imagine a divide function that errors if the y value is 0
main := () ! {
    x := divide(1,1).! // this propogates the error
    y := divide(1,0) or 1 // default value
    z := divide(1,0) or {} // do things without needing the error or one thing
    a := divide(1,0) or |e| {} // do thing(s) with the error
}
```

# Modularity
Dyn organizes its code into modules, and each file starts with the module
declaration

```
// in a.dyn
module alphabet
// rest of code
```

And each module holds the different declarations for said module

## Module Location
Modules are not only identified by name, but also by folder location
So a module at `src/module1` with the module name "alphabet" is different than
a module at `src/module2` with the name "alphabet." This becomes important in
using the module and also visibility of declarations within the module

## Declaration Visibility
All declarations in a module are visible to other declarations within the same
module and are hidden from all others by default. In order to give other modules
access to these declarations, prefix it with `pub`:

```
// in a.dyn
module alphabet

thing1 := () {} // only available in b.dyn
pub thing2 := () {} // available to anyone that uses this module

// in b.dyn
module alphabet

// both thing1 and 2 are visible here
thing3 := () {} // only usable in a.dyn, not anywhere else
```

## Using Modules
In dyn, using a module is as easy as creating a declaration, but the actual
expression to use a module is `use "[relative-loc]/[module-name]"`

```
// given the following file structure
src
    | a.dyn // alphabet module
    | b.dyn // alphabet module
    | main.dyn // main module

// in main.dyn
module main
alphabet := use "alphabet"
```

Another example:

```
// given the following file structure
src
    | alphabet
        | a.dyn // alphabet module
        | b.dyn // alphabet module
    | main.dyn // main module

// in main.dyn
module main
alphabet := use "alphabet/alphabet"
```

The goal of this is to give you flexibility in organizing the code, and it lets
you put multiple modules in one folder for locality's sake

Another thing to note when using modules is that the name of the variable also
can act as the alias

```
module main

alphabet1 := use "alphabet"
alphabet2 := use "alphabet"
// both aliases for the same module

main := () {
    alphabet1.thing2()
    alphabet2.thing2() // since thing2 is marked pub
}
```

And if you only want a specific item from the module:

```
thing2 := (use "alphabet").thing2 // use is an expression and can be accessed
```

# Metaprogamming
Dyn provides several ways to metaprogram, similar to how zig does it

## Types As Values
Dyn supports using `type` as a valid, well, type for variables and parameters
in functions, this means you can pass types (like u32, f32, arrays, named types)
as arguments into functions, as values for structs, or as variables too

```
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
Dyn does not support generics in the traditional sense, rather dyn supports the
ability to create types with "generic" parameters through function calls and
using type parameters. Below is a simple example:

```
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
Dyn also allows you to run code during compilation, this lets you do conditional
compilation, iterate out loops of code, and do tasks before runtime to prevent
extra calculations, this is triggered with the `comp` keyword

```
use_f64 := true // variable known at compile time
calc_pi := () comp if(use_f64) f64 else f32 { // the if is checked at comptime
    // return some amount of pi with calculations
}

main := () {
    pi := comp calc_pi() // run as a comp expression, will already be done since
                         // function already has compile time stuff in it though
}
```

A benefit of comp is that you can mark a type parameter, meaning the type it
uses needs to be known at compile time, which just adds safety and help with
code generation

### Inlining
You can also inline both functions and for loops in dyn as well and they will
get unrolled during compilation. There are a few caveats though:
- the values only apply to iterable expressions
- the values need to be known at compile time, which can also be an expression
  computed at compile time
In the case of functions, in order to have it inlined, specify that when
creating the function

```
fn_inlined := inline () {
    // anything in here will be printed out wherever the function is used
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

For for loops, the same kind of thing happens, but a little different:

```
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

TODO:
# Memory Management
# Concurrency
# Builtin Functions
# Type Coercion
# Interop
# Defer
