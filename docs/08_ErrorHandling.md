# Error Handling

Dyn supports errors and handling, and they do this specifically with functions, you declare that a function can error doing following.

```dyn
some_error_fn := () ! {}
some_returning_error_fn := () f32! {}
```

The ! tells dyn that this function can return back an error type, which gets inferred if there isnt anything after !

## Custom Error Types

In dyn, you can use either enums or structs as custom error types. To use them, list type after ! in function definition.

```dyn
SomeError := struct { things: i32, here: i32 }
an_error_fn := () f32!SomeError {} // specify multiple with ,
```

You can also specify several error types as well, separating them with !:

```dyn
SomeError := struct { things: i32, here: i32 }
SomeOtherError := enum {
    A_Thing,
    AnotherThing: f32,
    SubThing: struct {} // specifying a partner as an inline struct
}
an_error_fn := () f32!SomeError,SomeOtherError {} // specify multiple with !
```

## Handling Errors

To manage errors in current baseline, use `.!` or `or` with a fallback value expression.

`or` capture forms like `or |e| { ... }` are planned and not fully implemented yet.

```dyn
// imagine a divide function that errors if y value is 0
main := () ! {
    x := divide(1,1).! // this propogates error
    y := divide(1,0) or 1 // default value
    z := divide(1,0) or 2 // fallback expression
}
```
