# LANGUAGE SPECIFICATION (.dyn)

## 1. FILE & MODULE SYSTEM
- Extension: All source files must use the `.dyn` extension.
- Module Declaration: Every file must declare its module at the top (e.g., `module main`).
- Directory-Based Grouping: A single module is defined by the combination of a directory path AND the module name.
  - If `folder/a.dyn` and `folder/b.dyn` both declare `module math`, they are merged into one single `math` module namespace.
- Isolation: Files in the same directory with DIFFERENT module declarations are completely isolated from each other. They cannot see each other's private OR public members without explicitly importing them.
- Visibility: All variables, functions, and types are private to their module by default. They must be marked with `pub` to be exported (e.g., `pub usable_outside := 1`).
- Importing: Imports are assigned to a variable using the relative path and module name: `my_mod := use "path/to/module_name"`.

## 2. VARIABLES & MUTABILITY
- Variables are immutable by default.
- Assignment uses `:=` for type inference, or `: type =` for explicit typing, effectively : and = are different, and the type can be null (by just doing :=) to tell the compiler to infer the type if possible
- Mutability is strictly opt-in using the `mut` keyword (e.g., `mut total = 0` or `mut d: u1 = false`).

## 3. DATA TYPES
- Integers: Supports specific bit-widths (e.g., `i32`, `u1`, `i31`, `u8`).
- Floats: `f32`, `f64`, `f128`.
- Strings/Chars: Strings (`"hello"`) resolve to `[]u8`. Characters (`'a'`) resolve to `u8`.
- Arrays/Slices: Fixed arrays `[10]i32`. Slices `[]i32` (can be sliced via `i[0..2]` or `j[..]`).
- Tuples: Positional tuple literals use braces with commas (e.g., `{1, true, "x"}`) and are indexed with compile-time integer literals (`t[0]`).
- Pointers: `*i32` (immutable pointer) and `*mut u1` (mutable pointer). Dereferenced using `.*` (e.g., `q.* = false`).
- Optionals: Denoted with `?` (e.g., `?i32`).
  - Note: Any variable assigned `null` must technically be declared as mutable.

## 4. FUNCTIONS
- Syntax: `name := (args) ReturnType { ... }`
- Arrow Syntax: Single-expression functions can use `=>` instead of `{ return ... }`.
  - `=>` is only for expression bodies and must not be followed by a block (`{ ... }`).
- Extern Functions:
  - Binding-style form: `write := extern (fd: i32, ptr: *u8, len: usize) i32 = "dynrt_fd_write"`
  - Extern declarations are function-only (no extern variables).
- Default Arguments: Supported (e.g., `x: i32 = 0`).
- First-Class: Functions can be stored in structs (e.g., `fn_ptr := *fn(self: u)`), and can be passed as parameters: (`do_math := (x: i32, y: i32, math_fn: fn(x: i32, y: i32) i32)`) or can be returned from a function too (`math_builder := (the_fn: (x: i32, y: i32)i32) fn(x: i32, y: i32) => (x: i32, y: i32)i32 { val := the_fn(x,y)}`).

## 5. CUSTOM TYPES (STRUCTS & ENUMS)
- Structs: Anonymous definition assigned to a type variable: `s := struct { item: u32 }`.
  - Packed structs are supported: `s := packed struct { item: u32 }`.
  - Instantiated using dot notation: `.{}` or `TypeName{}`.
- Enums (Sum Types / Tagged Unions): Can hold complex payloads.
  - Definition: `r := enum { variant1, variant2: i32 }`.
  - Explicit representation type is supported with unsigned integer widths: `r := enum(u8) { A, B }`.
  - Instantiation: `r.variant2(5)` or `.variant2(5)` if the root enum can be determined.

## 6. CONTROL FLOW (EVERYTHING IS AN EXPRESSION)
### Universal Body Syntax (If/Else, Match, Loops, even defer)
- Curly braces are OPTIONAL for a single expression or single statement, but required for multi-statement blocks
- Note on "void" expressions: a single statement (like an assignment `a = 1`, a void function call, a for loop, or keywords like `break`) is treated like a valid single expression returning `void`
  - Example: `if condition do_thing() else a = 2`
  - Example:
    ```
    if condition {
        do_thing()
        a = 1
    }
    ```
- Branch Type Matching (Unification): Because everything is an expression, ALL branches in `if/else` and `match` statements must evaluate to the EXACT same type.
  - The Null/Optional Exception: If one or more branches evaluate to a specific type (e.g., `i32`), and another branch evaluates to `null`, the compiler must unify the overall expression's return type to be the Optional version of that type (e.g., `?i32`).
  - Match Example: `w := match total { 1: 1, _: null }` (The AI's Type Checker must infer `w` as `?i32` because it unified `i32` and `null`).

### If/Else
- If/Else: Can be used as statements or expressions (`v := if total % 2 == 0 total / 2 else 0`).
- Single-expression branches must not be wrapped in block braces.
  - Valid: `v := if cond value else other_value`
  - Invalid: `v := if cond { value } else other_value`

### Match:
- Match: `match total { 0..1: {}, _: {} }`.
  - Used to unwrap enums: `match res { .variant2: |val| {} }`.
  - Must be exhaustive or provide a default `_: {}` branch.

### Loops (`for`):
- Loops (`for`):
  - Ranges: `for 0..10: |v| {}`
  - Array Iteration: `for i: |v| {}`
  - While-style: `for total < 10: {}`
  - Infinite: `for {}`

### Blocks & Breaks/Continue
- Blocks & Breaks: Blocks can be labeled (`blk: {}`) and broken out of (`break :blk`).
- Continue may also carry a label (`continue :blk`) when targeting a labeled context.
- Blocks also have a type associated with them, and can either be broken with a value (`break :blk value`) or not (becomes a void block)

## 7. ERROR HANDLING
- Errorable Functions: Return types appended with `!` and an error enum (e.g., `f32!DivideError1,DivideError2`).
- Handling Errors:
  - Default value fallback: `A := divide(1,0) or 0`
  - Catch block: `C := divide(1,0) or { break 0 }`
  - Catch with error capture: `D := divide(1,0) or |err| { ... }`
  - Force Unwrap / Propagation: `divide(1,1).!`
    - In non-errorable functions, `.!` traps on error.
    - In errorable functions, `.!` propagates the error to caller.
    - Propagated errors must be covered by the function's declared error set.

## 8. OPTIONAL HANDLING
- Force unwrap: `n.?`
- Fallback/Default: `n or 1` or `n or { break 1 }`
- Safe if-unwrapping: `if n: |v| {}` (ignores block if null). `if n: |_| {}` to discard value.

## 9. COMPILE-TIME (COMPTIME) & METAPROGRAMMING
- Types are First-Class: Generics are achieved by passing `type` as a function argument (e.g., `List := (T: type) type => struct {}`).
- Comptime Evaluation: Prefixing an expression with `comp` forces compile-time execution (`pi := comp calc_pi()`). If evaluation fails, compilation fails with an error (no runtime fallback).
- Inline Execution: Supported inline forms are `inline for <range>`, direct inline calls, and inline function literals.
  - `inline for` requires compile-time-evaluable range bounds.
  - Inline calls must lower as inline expansions; if they cannot, compilation fails (no normal-call fallback).
- `$Self()` can refer to the current instantiating type.

## 10. DEFER
- Executes block at the end of the current scope in LIFO order (last in, first out).
- Syntax: `defer {}`.
- Error-only defer: `defer |e| {}` executes *only* if the scope exits via an error.

## 11. COMMENTS & DOCUMENTATION
- Line Comments: `// comment` (Ignore during lexing)
- Block Comments: `/* comment */` (Ignore during lexing)
- Doc Comments: `/// comment` (The lexer MUST capture these as `DOC_COMMENT` tokens so the parser can attach them to the next node).

## 12. COMPILER BUILT-INS (INTRINSICS)
- Prefix: All special compiler built-in functions are prefixed with `$`.
- The Lexer should tokenize words starting with `$` as a special `BUILTIN_IDENTIFIER`.
- Core Built-ins:
  - Casting: `$as(Type, value)` (e.g., `$as(f32, 5)` converts integer 5 to float 5.0).
  - Std-owned Printing: printing is provided by imported modules, not compiler-recognized global names.
    - Example: `io := use "std/io"` then `io.println("Hello, world")`.
    - `print(...)` / `println(...)` are unresolved unless user code defines them explicitly.
  - Type Info: `$typeof(expr)` (Returns the type of the expression).
  - Memory: `$sizeof(Type)`, `$alignof(Type)`, `$offsetof(Type, field_name)`.
  - State: `$unreachable()` (Marks code paths that should never execute).
  - Comptime: `$compile_error("msg")` (Triggers a user-defined compiler error).
  - Error: `$panic("msg")` (Panics at the location during runtime)
- Note: `$Self()` is a special built-in used inside struct/type definitions to refer to the instantiating type.
