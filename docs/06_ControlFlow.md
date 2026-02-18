# Control Flow

Dyn offers a couple options for control flow.

## Status

This chapter mixes implemented behavior and planned behavior.

Implemented baseline today:

- `for <bool-expr> { ... }` condition loops
- `for { ... }` infinite loops
- range-based iterable loop: `for a..b: |i| ...` and `for a..=b: |i| ...`
- slice-form iterable loop with explicit bounds: `for p[lo..hi]: |v| ...`
- named slice-binding iteration: `s := p[lo..hi]` then `for s: |v| ...`
- `break` and `continue` (including labels)
- `if` expressions and `match` expressions

Planned/not fully implemented yet:

- non-range iterable `for` forms beyond pointer/slice-style loops (arrays/other iterables)
- full `match` exhaustiveness/overlap checking

## For

Only one loop is offered in dyn: `for`. In the current baseline it acts as a while-style loop (`for <bool-expr>`) or infinite loop (`for { ... }`).

### As Iterable

```dyn
main := () {
    for 0..10: |i| {
        // do things with i
    }
}
```

Range iteration is implemented. Example:

```dyn
main := () {
    mut sum: i32 = 0
    for 0..10: |i| {
        sum += i
    }
}
```

You can also use single statements for a for loop as well:

```dyn
main := () {
    mut sum: i32 = 0
    for 0..10: |i| sum += i
}
```

Multiple iterable conditions are planned, not currently implemented:

```dyn
main := () {
    for 0..10, 0..10: |i, j| {}
}
```

Matching iterable lengths/capture arity checks are planned with iterable-loop implementation.

```dyn
main := () {
    // for 0..10, 0..10: |i| {} - invalid
    for 0..10, 0..10: |i, _| {} // valid
}
```

Array iteration syntax is planned, not currently implemented:

```dyn
main := () {
    x: []i32 = [1,2,3,4,5]
    for x: |i| {
        // do something with value in x
    }
}
```

Capture mutability for iterable loops is planned, not currently implemented:

```dyn
main := () {
    x: []i32 = [1,2,3,4,5]
    for x: |i| {
        // cannot do i += 1
    }
    for x: |mut i|  i += 1 // now you can because i is marked as mut
}
```

### As Condition (Implemented)

As mentioned above, dyn uses for loops also in place of while loops, so you can do something like following:

```dyn
main := () {
    mut x := 1
    for x < 10 x += 1
}
```

Current baseline supports a single boolean condition expression (which can itself use `&&`/`||`) or an infinite loop form.

And if you do a for loop with a block and no condition, it acts like an infinite loop.

```dyn
main := () {
    for {
        // do something forever
        break // please make sure to break these
    }
}
```

## If

If statements are branching logic pieces that execute based on given logic.

```dyn
something := 1
if something == 1 {
    // do something
} else {} // else optional for statements
```

You also dont need {} if it's a single statement/expression.

```dyn
mut something := 1
if something == 1 something = 2
```

This also applies to else's too:

```dyn
if something == 1 something = 2 else something = 3
if something == 1 something = 2 else if something == 2 something = 3 else something = 4
```

Ifs can also be used as expressions, doing so this way requires an ending else, regardless of amount of else/ifs and each branch needs to evaluate to same type.

```dyn
x := if something == 1 1 else 0
```

Since ifs as expressions have to evaluate to same type, blocks used also need to evaluate to same type.

```dyn
y := if something == 1 { // y evaluates to an int
    // do something else here if you want
    break 1 // int
} else {
    // do something else here too if you want
    break 0 // int
}
```

Only time this changes is with optional types since it's allowed to be a null or a value.

```dyn
z := if something == 1 { // y evaluates to a ?int
    // do something else here if you want
    break 1 // int
} else {
    // do something else here too if you want
    break null
}
```

Ifs can be used for optional types as well, so you can do something like this:

```dyn
maybe := null
if maybe: |v| {
    // do something with v
} else {} // if maybe is null
```

## Match

Match statements give you ability to execute code based on a series of patterns and a value that gets matched against them. All values arrays, void or struct types can be matched against. Patterns you match against need to be same type as value you match.

```dyn
main := () {
    val: i32 = 2
    match val {
        1: {}, // a pattern to match, i32
        2..=10: {}, // another pattern, still seen as i32
        _: {} // default, covers all other cases
    }
}
```

Another thing to note with patterns being same type, this also corresponds to int types of varying bit representations, so if you match on a u8, you can only match up to a u8's values, and nothing below 0, same with i8 or u/i32, etc.

Match exhaustiveness/overlap enforcement is planned and not fully implemented in the current baseline.

### Enum Matching

Enums are matched just by listing variant. If enum variant has a partner, then that value can be captured, both immutably and mutably.

```dyn
SomeEnum := enum {
    variant1: i32,
    variant2: f32,
    variant3
}

main := () {
    thing := SomeEnum.variant1(i32)
    match thing {
        .variant1: |i| {},
        .variant2: {}, // if you dont want to use partner, dont include
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

```dyn
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

Values being returned need to be same type, at least as far as being ints or being all floats, etc except for having an optional type or error.
