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

