# Dyn rules

Every rule of the language, in one list. A rule that is not here does not exist; the
[language reference](language.md) gives the details and examples for each one. Library
behavior (std, vendor) is not language and is documented with each module.

## Names and declarations

1. **One namespace per module.** Functions, globals, types and constants share it. Struct
   fields and enum variants have their own scope.
2. **No shadowing.** A local cannot reuse the name of a local, parameter or loop variable that
   is still in scope, or of a global, function or module. A name is free again once its block
   or loop ends.
3. **`:=` declares a mutable local from its value; `name: T` declares one of type `T`.**
   `const` names a compile-time constant. Parameters are mutable copies.
4. **Zero is a valid value of every type.** A declaration without a value is zero, or its
   struct's field defaults. `#init(p)` makes `*p` that same fresh value.
5. **Types are written in full, with one shorthand.** A struct literal always names its type,
   there are no local type aliases, and generic types are inferred only from call arguments, or
   from the function type a generic function is used as. `Enum.Variant` names its enum; where
   exactly one enum type is expected, `.Variant` is enough.
6. **Generics take `<T>`.** Functions, structs and enums declare type parameters in angle
   brackets; a call infers them from its arguments or writes them, `mem.push<Node>(arena)`.

## Values and conversions

7. **Conversions are implicit only when lossless on every target.** `usize` and `isize` count as
   anywhere from 32 to 64 bits. Everything else needs `#cast`.
8. **Literals take the type they go into.** With nothing to go into, an integer literal is
   `i32`, a float literal `f64`, a character literal `u32` and a string `[]const u8`. A range of
   two literals counts in `usize`.
9. **Mixed number operands meet at the wider type** when one widens to the other without loss.
10. **Arithmetic is target-typed.** Where a value goes into a wider number type, the operators
   compute in that type. `#cast` and `:=` give no target.
11. **Signed and unsigned integers compare by value.** One operand is read twice, so at least one
    side must contain no calls.
12. **Three operators narrow without a cast** where their range fits: `x & M`, unsigned `x >> k`
    and unsigned `x % M` with a constant `M` or `k`.
13. **Integer arithmetic wraps.** `--check-overflow` turns overflow of `+ - * <<` and negation
    into a panic in every module, std included; arithmetic inside `#wrapping(...)` still wraps.
    Division by zero always panics.
14. **`*const T` and `[]const T` are shallow.** They forbid writes through that view only.
    `*T` converts to `*const T` and to `rawptr`, never back.

## Evaluation

15. **Everything evaluates left to right, once, in written order:** arguments, struct literal
    fields, operands, range bounds and steps, the target of an assignment before its value, and
    the subject of a `case`.
16. **`&&` and `||` short-circuit.**

## Control flow

17. **`if` and `for` conditions are `bool`.** There is no truthiness.
18. **`for` has four forms:** condition, infinite, range (`a..b`, `a..=b`, with `#reverse` and
    `#step`), and over an array or slice (`for value in values`, `for *value`, `for value, i`).
19. **`break` and `continue` act on the innermost loop, or on the loop their label names**
    (`break outer`). A `for` with no condition and no `break` leaves only by `return` or a panic,
    so no `return` needs to follow it.
20. **`case` on an enum lists every variant or has `_`; `case` on an integer or text always has `_`.**
21. **`defer` runs at block exit, last first,** on every exit: fall-through, `return`, `break`,
    `continue`.
22. **`#panic` and failed run-time checks end the program.** They print a message and trace and
    call the handler set with `panic.set_handler`; they do not run defers.

## Errors

23. **A function that can fail returns `T!E`.** `E` is an enum or a union of enums (`A | B`);
    `T!` and `!` fail with no value. Failure is a return value: no exceptions, no unwinding.
24. **Every failure is handled.** `try` passes it on, `catch fallback` replaces it with a value,
    and `catch err { ... }` handles it; a block on a call with a value must leave with `return`,
    `fail`, `break`, `continue` or `#panic`. `errdefer` runs only when the function fails.

## Memory

25. **No hidden allocation.** Memory comes from arenas or storage you declare. Returning or
    storing the address of a local where it outlives the function is an error.
26. **Bounds, nil and alignment are always checked.** `#slice(pointer, count)` makes a pointer
    range you vouch for, and indexing it is checked against that count.
27. **A `nocopy` type is never copied.** Borrow it with `&value`; `#take(&value)` moves it out
    and leaves `value` fresh.

## The compiler

28. **No code is special.** The compiler treats every module the same, whatever its name or path.
    Std, core and heap are ordinary Dyn code that anyone could write.
29. **Builtins start with `#`** and exist only for what the compiler must provide: `#cast`,
    `#bitcast`, `#wrapping`, `#sizeof`, `#alignof`, `#offsetof`, `#typeof`, `#slice`, `#init`,
    `#take`, `#assert`, `#panic`, `#syscall`, `#reverse`, `#step`, `#max`, `#min`, `#load`,
    and `#sqrt`, `#floor`, `#ceil`, `#trunc`, `#round`, `#fma` where hardware has the
    instruction. File directives: `#target` and `#link`.
30. **Debug and release run valid programs the same way.** Debug adds information for debuggers;
    neither mode changes the meaning of a program.
