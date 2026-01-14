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

Matches can also be used as expressions, just like ifs can:
```
main := () {
    val: i32 = 2
    result := match val { // type of result is ?[]u8
        1: "world",
        2: "hello",
        3: {
            break "uh oh"
        },
        _: null
    }
}
```
Values being returned need to be the same type, at least as far as being ints
or being all floats, etc except for having an optional type or error
