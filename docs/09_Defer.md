# Defer

Defer lets you effectively queue things to do at end of a function call just before it returns back to caller. Actions that are deferred get queued in reverse order that they are called.

```dyn
main := () {
    defer {} // happens last
    defer {} // happens third
    defer {} // happens second
    defer {} // happens first
    return // this happens before defers
}
```

Defers can be single statements or they can be blocks of statements. You cannot defer statements that would break function scope, so things that propagate an error/null, or return statements cannot be used since function is already going back to caller.

Dyn also lets you defer only on error, by specifying a capture on defer block dyn will only queue block on fail and bind error to name specified in capture.

```dyn
main := () ! {
    defer |e| {} // queues only on error and error is bound to e
    defer |_| {} // queues only on error but will not bind error
}
```
