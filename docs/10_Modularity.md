# Modularity

Dyn organizes its code into modules, and each file starts with module declaration.

```dyn
// in a.dyn
module alphabet
// rest of code
```

And each module holds different declarations for said module.

## Module Location

Modules are not only identified by name, but also by folder location. So a module at `src/module1` with module name "alphabet" is different than a module at `src/module2` with name "alphabet." This becomes important in using module and also visibility of declarations within module.

## Declaration Visibility

All declarations in a module are visible to other declarations within same module and are hidden from all others by default. In order to give other modules access to these declarations, prefix it with `pub`:

```dyn
// in a.dyn
module alphabet

thing1 := () {} // only available in b.dyn
pub thing2 := () {} // available to anyone that uses this module

// in b.dyn
module alphabet

// both thing1 and 2 are visible here
thing3 := () {} // only usable in a.dyn, not anywhere else
```

## Using Modules

In dyn, using a module is as easy as creating a declaration, but actual expression to use a module is `use "[relative-loc]/[module-name]"`.

```dyn
// given following file structure
src
    | a.dyn // alphabet module
    | b.dyn // alphabet module
    | main.dyn // main module

// in main.dyn
module main
alphabet := use "alphabet"
```

Another example:

```dyn
// given following file structure
src
    | alphabet
        | a.dyn // alphabet module
        | b.dyn // alphabet module
    | main.dyn // main module

// in main.dyn
module main
alphabet := use "alphabet/alphabet"
```

Goal of this is to give you flexibility in organizing code, and it lets you put multiple modules in one folder for locality's sake.

Another thing to note when using modules is that name of variable also can act as alias.

```dyn
module main

alphabet1 := use "alphabet"
alphabet2 := use "alphabet"
// both aliases for same module

main := () {
    alphabet1.thing2()
    alphabet2.thing2() // since thing2 is marked pub
}
```

And if you only want a specific item from module:

```dyn
thing2 := (use "alphabet").thing2 // use is an expression and can be accessed
```
