# Types

## Simple Types

### Integers

In dyn, integer types are specified as `[u or i][number of bits]` u for unsigned and i for signed. This grants you more control over how much data gets used in program. If int is signed, number reserves 1 bit as sign bit and rest is reserved for number, which means a signed integer will have a max value of `2^(i-1)-1` where i is number of bits.

But, dyn prefers "accurate representation" over convenience in a couple places, namely, booleans and characters.

#### Booleans

Booleans (true and false) are represented as an unsigned 1 bit int, and is typed as such. So booleans are just `u1`, and can be set to either 1, 0, true, or false.

#### Characters

Characters are represented as either u8-u32 (1 byte to 4 bytes), with most English using just 1 byte, but, just like booleans, type for a character is just `u8-32`.

#### Literal Representations

In dyn, integer literals can be represented as follows:

- As just a number: `1000`
- With \_ in them: `1_000`
- Binary: `0b1111101000`
- Octal: `0o1750`
- Hex: `0x3E8`

### Floats

Floats are decimal numbers, and they follow IEEE single `f32` or double `f64` or quadruple `f128` precision specifications.

## Complex Types

### Arrays

Arrays are continuous values of same type, specified with `[number]typename`, they are specified as a pointer and a length.

#### Slices

Slices are peeks into an array, stored with a pointer and a start, and a length, specified with `[]typename`.

#### Strings

Strings are just arrays or slices of characters, which as above, would be either `[]u8-32`.

### Optional

Optionals represent either a value or nothing, but it's useful for when something doesnt always need to exist, specified with `?typename`.

#### Null

This is empty value when an optional isnt meant to have anything, specified with `null`.

#### Handling Optionals

You can handle an optional either by unwrapping it and propagating null with `.?` or you can use an or block or you can use and if statement (see below).

```dyn
a: ?i32 = null
x := b.? // this propogates null
y := b or 1 // default value (could also be used for single statement)
z := b or {} // do thing(s)
```

If you want to assign a value to an optional type, you just need to assign it, there's no optional dereferencing required.

```dyn
opt_val: ?i32 = null // you need to specify type if youre assigning to null
a := opt_val or 1 // type on or needs to match unless void statement, a = 1
opt_val = 2
b := opt_val or 1 // b = 2
```

### Pointer

Pointers are values that hold address to a value of a given type, they are stored as size of architecture's bit processing (32 for 32 bit systems, 64bits for 64 bit systems) and they can be dereferenced to access value being pointed to to access value. Pointers can be used with both stack or heap.

```dyn
a_val: i32 = 4
a_pointing_val := &a_val // returns *i32
```

The address of operator (& prefix) will return either a pointer or a mutable pointer of type that youre getting address of. Note that you can only create a mutable pointer (`*mut T`) if original variable is declared as mutable (`mut`). To create an immutable pointer, original variable can be either mutable or immutable.

```dyn
mut a_val: i32 = 4
a_pointing_val := &a_val // returns *mut i32
a_readonly_pointing_val: *i32 = &a_val // *i32 even if var is mutable

b_val: i32 = 4  // immutable
c_ptr := &b_val  // returns *i32 (cannot be *mut since b_val is not mut)
// mut_ptr := &b_val  // ERROR: cannot create mutable pointer to immutable variable
```

In order to use value that's pointed to by pointer, you need to dereference it:

```dyn
mut a_val: i32 = 4
a_pointing_val := &a_val
b := a_pointing_val.*
```

If pointer is a mutable one (`*mut i32` for example), then data being dereferenced can be changed.

```dyn
mut a_val: i32 = 4
a_pointing_val := &a_val
a_pointing_val.* = 5
```

In dyn, you can have multiple immutable pointers to a piece of data or you can have one mutable pointer to a piece of data, it will error otherwise. Pointers also cannot point to nothing unless it's an optional type.

Dyn will also try to track pointers to verify that they are used and that there is always a pointer to allocated data, preventing leaks.

### Mutability Rules and Scenarios

The mutability system follows these rules:

- **One mutable pointer OR multiple immutable pointers** to any piece of data
- This applies transitively through struct nesting

#### Scenario 1: Multiple Immutable Pointers (Allowed)

```dyn
data := struct {
    values: [5]i32,
    count: u64
}

items := data{ values: [1,2,3,4,5], count: 5 }

// Multiple immutable pointers are fine
ptr1 := &items
ptr2 := &items
ptr3 := items.values.ptr // Even nested pointers work

// All can read, none can modify
x := ptr1.count  // OK
// ptr1.count = 6  // ERROR: ptr1 is immutable
```

#### Scenario 2: Single Mutable Pointer (Allowed)

```dyn
items := data{ values: [1,2,3,4,5], count: 5 }

// One mutable pointer
mut_ptr := &items

// Can modify through mutable pointer
mut_ptr.count = 6  // OK

// Cannot create another pointer (immutable or mutable)
// ptr2 := &items  // ERROR: data already has mutable pointer
```

#### Scenario 3: Structs with Pointers

The rule applies transitively - if a struct has a pointer member, parent follows same rules:

```dyn
Node := struct {
    value: i32,
    next: ?Node,  // This contains a pointer implicitly
}

// Creating two nodes
node1 := Node{ value: 1, next: null }
node2 := Node{ value: 2, next: null }

// Linking: only one node can have a mutable pointer to other
node1.next = node2  // OK: node2 now owned by node1's next

// ERROR: Can't create another pointer to node2
// ptr2 := &node2  // Would violate single-mutable rule

// But we can have multiple immutable pointers to node1 (since it doesn't point to node2 mutably)
r1 := &node1
r2 := &node1  // OK: both immutable
```

#### Scenario 4: Reclaiming Mutability

You can reclaim mutability by "forgetting" original reference:

```dyn
items := data{ values: [1,2,3,4,5], count: 5 }

// Create immutable pointer
ptr1 := &items

// "Move" value to reclaim mutability
items2 := items  // items is now invalid
ptr2 := &items2  // OK: items2 has no other pointers
```

#### Scenario 5: Optional Pointers

Optional pointers provide flexibility but still enforce mutability rules:

```dyn
mut data := data{ values: [1,2,3,4,5], count: 5 }

// Optional pointer that's null
maybe_ptr: ?data = null  // OK

// Now assign to it
maybe_ptr = data  // data is now "moved" into maybe_ptr

// Cannot access data anymore
// data.count = 6  // ERROR: data was moved

// But can modify through optional
maybe_ptr.count = 7  // OK: maybe_ptr is mutable
```

### Enums

Enums types are a variant-based, fixed set of values, defined as follows:

```dyn
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

```dyn
today := Week.Monday // Week is optional if variant is inferrable
```

Enum variants can be partnered with a payload type, effectively creating a tagged union.

```dyn
Message := enum {
    Success,
    Warning: []u8,
    ErrorCode: enum { Unauthorized, Invalid } // use enum as literal expression
}
```

To select a variant from an enum with a partner, do following:

```dyn
variant := .Warning("This is a warning message") // omittable if enum inferred
```

### Structs

Structs are types with blocks of related data pieces. In dyn struct literals are expressions, defined as follows:

```dyn
AStruct := struct {
    item1: i32,
    item2: i32,
    item3: i32
}
```

Struct members can also be grouped together if types are similar:

```dyn
AStruct := struct {
    item1, item2, item3: i32,
}
```

And these members can have a default value:

```dyn
AStruct := struct {
    item1, item2, item3: i32 = 0, // can be done for grouped vals
    other: u8 = 'a', // or for single ones
}
```

To instantiate a struct, do following:

```dyn
x := AStruct{ item1: 1, item2: 2, item3: 3 } // other will still be 'a'
y := AStruct{ other: 'b' } // item1,2,3 = 0 and other is 'b'

// to access a member of a struct:
x.item1
y.other // can be used to get or set
```
