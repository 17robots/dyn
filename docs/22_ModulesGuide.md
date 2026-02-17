# Dyn Modules Guide

## Module model

A module is all `.dyn` files in a directory that share the same `module <name>` declaration.

Example directory:

```text
app/
  main.dyn      (module main)
  util_a.dyn    (module util)
  util_b.dyn    (module util)
```

`util_a.dyn` and `util_b.dyn` are in the same `util` module.

## Imports

`use "path/to/modname"` resolves as:
- directory: `path/to`
- module name: `modname`

The compiler loads all `.dyn` files in that directory and selects files declaring `module modname`.

If none are found, import fails.

For `use "std/..."`, the CLI flag `--std-dir <dir>` provides an optional fallback root.
Resolution order is local relative import first, then `--std-dir` fallback.

## Example

`main.dyn`

```dyn
module main

L := use "lib"
main := () i32 => L.helper()
```

`lib.dyn`

```dyn
module lib

pub helper := () i32 => 27
```

## Visibility

Only `pub` declarations are available through an import alias.
Accessing non-public members through `Alias.member` is a resolver error.
