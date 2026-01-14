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

