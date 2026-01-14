# Defer
Defer lets you effectively queue things to do at the end of a function call
just before it returns back to the caller. Actions that are deferred get queued
in reverse order that they are called

```
main := () {
    defer {} // happens last
    defer {} // happens third
    defer {} // happens second
    defer {} // happens first
    return // this happens before the defers
}
```

Defers can be single statements or they can be blocks of statements. You cannot
defer statements that would break the function scope, so things that propagate
an error/null, or return statements cannot be used since the function is already
going back to the caller

Dyn also lets you defer only on error, by specifying a capture on the defer
block dyn will only queue the block on fail and bind the error to the name
specified in the capture

```
main := () ! {
    defer |e| {} // queues only on error and error is bound to e
    defer |_| {} // queues only on error but will not bind the error
}
```

