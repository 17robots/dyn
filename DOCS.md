# Getting Started
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
```
break fn match defer struct enum if for continue use mut for
```
## Terminators
Dyn
## Block Rules
## Operator Precedence
# Types
## Simple Types
### Integers
In dyn, integer types are specified as `[u or i][number of bits]` u for unsigned
and i for signed. This grants you more control over how much data gets used in
the program. If the int is signed, the number will be that many bits and have
an additional sign bit added on, so signed requires one more bit to store
But, dyn prefers "accurate representation" over convenience in a couple places,
namely, booleans and characters
#### Booleans
Booleans (true and false) are represented as an unsigned 1 bit int, and is typed
as such. So booleans are just `u1`, and can be set to either 1, 0, true, or false
#### Characters
Characters are represented as either u8-u32 (1 byte to 4 bytes), with most English
using just 1 byte, but, just like booleans, the type for a character is just `u8-32`
#### Literal Representations
In dyn, integer literals can be represented as follows:
```
// as just a number
1000
// with _ in them
1_000
// binary
0b1111101000
// octal
0o1750
// hex
0x3E8
```
### Floats
Floats are decimal numbers, and they follow IEEE single (represented by f32) or double (f64) or quadruple (f128) precision specifications
```
float1 : f32 = 1.0
float2 : f64 = 1.0
float3 : f128 = 1.0
```
## Complex Types
### Arrays
Arrays are continuous values of the same type, specified with `[number]typename`, they are specified as a pointer and a length
#### Slices
Slices are peaks into an array, stored with a pointer and a start, and a length, spcified with `[]typename`
#### Strings
Strings are just arrays or slices of characters, which as above, would be either `[]u8-32`
### Optional
Optionals represent either a value or nothing, but it's useful for when something doesnt always need to exist, specified with `?typename`
#### Null
This is the empty value when an optional isnt meant to have anything, specified with `null`
### Pointer
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
Enum variants can be partnered with a payload type, effectively creating a tagged union
```
Message := enum {
    Success,
    Warning: []u8,
    ErrorCode: enum { Unauthorized, Invalid } // use enum as literal expression
}
```
To select a variant from an enum with a partner, do the following:
```
variant := .Warning("This is a warning message") // again ommittable if enum can be inferred
```
### Structs
Structs are types with blocks of related data pieces. In dyn struct literals are expressions, defined as follows:
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
Variables are names that hold values, all variables have values and a type telling dyn which kind of values the variable can hold
```
// ways to create variables
x: i32 = 1 // specify the type
y := 1 // infer the type
```
Variables in dyn are immutable by default, so `x = 0` will error unless it is specified mutable:
```
mut z := 1 // can still infer type
z = 0 // can now change without error
```
# Math
# Control Flow
Dyn offers a couple options for control flow
## If
## For
## Match
# Functions
Functions in dyn operate the same as other variables, they are first-class citizens in dyn
## Construction
```
// functions are assigned as any other variable
add := (x: i32, y: i32) { // void types dont need anything specified
    // print adding x and y
}
add2 := (x: i32, y: i32) i32 { // specify the return type after the ) and before the {
    return x + y
}
add3 := (x,y: i32) i32 { // make functions easier with grouping names with similar type
    return x + y
}
add4 := (x,y: i32) i32 => x + y // and if you just have one thing to return, make it easier with => and the expression
add5 := (x,y: i32 = 0) => x + y // you can specify default values for a function, including to grouped identifiers
```
## Calling
# Error Handling
# Modularity
# Metaprogamming
