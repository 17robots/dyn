# Variables

Variables are names that hold values, all variables have values and a type telling dyn which kind of values the variable can hold.

```dyn
// ways to create variables
x: i32 = 1 // specify the type
y := 1 // infer the type
```

Variables in dyn are immutable by default, so `x = 0` will error unless it is specified mutable.

```dyn
mut z := 1 // can still infer type
z = 0 // can now change without error
```

Variables cannot be set to a value outside of the type assigned to the variable, even if inferred.

```dyn
mut a := 1
a = 1.0 // not allowed
// but since characters and booleans are also integer values, they can be set
a = 'a' // valid, but would be the int val instead of the character value
```

Variables also only exist in the scope they are defined, and cannot be used outside of that scope.

```dyn
a := 1
{
    b := 2 + a // a valid here
}
// c := b + a // b invalid here
```
