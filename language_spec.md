# LANGUAGE SPECIFICATION (.dyn)

## 1. FILE & MODULE SYSTEM
- Extension: All source files must use the `.dyn` extension.
- Module Declaration: Every file must declare its module at the top (e.g., `module main`).
- Directory-Based Grouping: A single module is defined by the combination of a directory path AND the module name.
  - If `folder/a.dyn` and `folder/b.dyn` both declare `module math`, they are merged into one single `math` module namespace.
- Isolation: Files in the same directory with DIFFERENT module declarations are completely isolated from each other. They cannot see each other's private OR public members without explicitly importing them.
- Visibility: All variables, functions, and types are private to their module by default. They must be marked with `pub` to be exported (e.g., `pub usable_outside := 1`).
- Importing: `use "path/to/module_name"` is an expression that evaluates to the module's namespace. It can be assigned to a variable, returned from a function, or used inline anywhere an expression is valid.
  - `my_mod := use "path/to/module_name"` — module-level binding.
  - `io := use "std/io"` inside a function body — scoped to that function.
  - `get_interface := (is_windows: u1) type => if is_windows use "std/windows" else use "std/linux"` — conditional import.

## 2. VARIABLES & MUTABILITY
- Variables are immutable by default.
- Assignment uses `:=` for type inference, or `: type =` for explicit typing. `:` and `=` are distinct tokens; omitting the type (`:=`) tells the compiler to infer it.
- Mutability is strictly opt-in using the `mut` keyword (e.g., `mut total = 0` or `mut d: u1 = false`).
- Null assignment rules (local variables only):
  - If the initial value is `null`, the variable **must** be declared `mut` and the type **must** be explicitly annotated (e.g., `mut o: ?i32 = null`). The type cannot be inferred from `null` alone.
  - Any local variable with a nullable type (`?T`) must have its type explicitly annotated.
  - Example — invalid: `o := null` (no type, no mut). Valid: `mut o: ?i32 = null`.
  - Struct fields are exempt from this rule — they always have explicit type annotations and don't require `mut` on the field definition itself.
- Destructuring:
  - Tuple / positional: `{a, b} := tuple_fn()` — binds `a` to index 0 and `b` to index 1 of the result.
  - Named struct: `{x, y} := point` — binds `x` and `y` by matching field names on the RHS struct.
  - `mut` can prefix individual names: `{mut a, b} := expr`.

## 3. DATA TYPES
- Integers: Arbitrary bit-width signed and unsigned integers (e.g., `i8`, `i16`, `i32`, `i64`, `u1`, `u8`, `u16`, `u32`, `u64`, `i31`, etc.).
  - Platform-sized: `usize` (unsigned pointer-sized integer) and `isize` (signed pointer-sized integer) are keywords.
  - Arithmetic uses **wrapping semantics** — overflow wraps around silently. No trapping on overflow.
- Floats: `f32`, `f64`, `f128`.
- Bool: `bool` is an alias for `u1`. `true` and `false` are `u1` literals (the same way `'a'` is a `u8` literal). There is no separate boolean type.
- Strings/Chars: Strings (`"hello"`) resolve to `[]u8`. Characters (`'a'`) resolve to `u8`.
  - Storage: An immutable string binding is stored in the binary's read-only data segment. A `mut []u8` binding is stored on the stack (or heap if explicitly allocated).
- Void: `void` is a keyword representing the absence of a value. Functions that do not return a value have return type `void`. Omitting the return type in a function declaration is equivalent to writing `void`.
- Arrays/Slices: Fixed arrays `[10]i32`. Slices `[]i32` (can be sliced via `i[0..2]` or `j[..]`).
- Tuples: `{val1, val2, val3}` is an anonymous positional struct literal — equivalent to `.{}` with unnamed positional fields. Indexed with compile-time integer literals (`t[0]`). The type of `{1, true, "x"}` is an anonymous struct with three positional fields.
- Pointers: `*i32` (immutable pointer) and `*mut u1` (mutable pointer). Dereferenced using `.*` (e.g., `q.* = false`).
  - Address-of: `&expr` produces a pointer to the value. On an immutable binding it gives `*T`; on a `mut` binding it gives `*mut T`. Example: `p: *i32 = &a`, `q: *mut u1 = &d`.
  - Coercion: `*mut T` implicitly coerces to `*T` (safe — only adds a restriction). The reverse is not implicit; use `$as(*mut T, ptr)` to force it when necessary.
  - Erased pointer: `*any` — a pointer to a value whose type has been erased. Used for dynamic dispatch and type-erased interfaces. Cannot be dereferenced directly; must be cast to a concrete pointer type first via `$as(*T, ptr)`. There is no `*mut any` — mutability is a property of the concrete type you cast to.
- Optionals: Denoted with `?` (e.g., `?i32`). The `null` literal represents the absent case. See §2 for null assignment rules.

## 4. FUNCTIONS
- Syntax: `name := (args) ReturnType { ... }`
- Return type is **required** for non-void functions. Omitting the return type means the function returns `void` — the compiler does NOT infer the return type from the body.
  - Valid void: `f := () {}` or `f := () void {}`
  - Valid non-void: `add := (x: i32, y: i32) i32 { return x + y }`
  - Invalid: `add := (x: i32, y: i32) => x + y` — no return type, so this is void; the expression result is discarded.
  - Valid non-void arrow: `add := (x: i32, y: i32) i32 => x + y`
- Arrow Syntax: `=>` can replace `{ return expr }` for single-expression bodies. The return type must still be declared (unless void).
  - `=>` must not be followed by a block (`{ ... }`).
- Errorable void: `main := () ! { ... }` — returns void but can propagate errors. `!` alone means the error set is inferred from the body (see §7).
- Extern Functions:
  - Binding-style form: `write := extern (fd: i32, ptr: *u8, len: usize) i32 = "dynrt_fd_write"`
  - Extern declarations are function-only (no extern variables).
- Default Arguments: Supported (e.g., `x: i32 = 0`).
- Named Arguments: Call sites may pass arguments by name in any order (e.g., `add3(y: 1, x: 2)`). The compiler validates that named arguments match declared parameter names.
- First-Class Functions: `fn(params) ReturnType` is the function type. It is valid anywhere a type is valid — parameter annotations, struct fields, return types, and variable bindings.
  - **Fat pointer representation**: Every `fn(...)` value is always two words: a function pointer and an environment pointer. This is true regardless of whether the function captures variables. Non-capturing functions have a null environment pointer; the type is the same either way.
  - **Closures**: A lambda that references variables from the enclosing scope automatically captures them. The captured variables are stored in a heap- or stack-allocated environment struct; the environment pointer in the fat pointer points to that struct.
  - **Non-capturing functions**: Named functions and lambdas that do not close over any variable have a null environment pointer. They are assignment-compatible with `fn(...)` types.
  - Example parameter: `do_math := (x: i32, y: i32, math_fn: fn(x: i32, y: i32) i32) i32 { ... }`
  - Example struct field: `fn_ptr: fn(self: s) void`
  - Example return type: `math_builder := (the_fn: fn(x: i32, y: i32) i32) fn(x: i32, y: i32) i32 { ... }`
  - Example closure: `make_adder := (n: i32) fn(x: i32) i32 => (x: i32) i32 => x + n` — the returned lambda captures `n`.
- Comptime Return Type: Prefixing the return type with `comp` means the return type expression is evaluated at compile time. The function produces a value whose concrete type is resolved at the call site.
  - Example: `calc_pi := () comp if use_f64 f64 else f32 => 3.14` — the return type is either `f64` or `f32` depending on the comptime flag.

## 5. CUSTOM TYPES (STRUCTS & ENUMS)
- Structs: Anonymous definition assigned to a type variable: `s := struct { item: u32 }`.
  - Packed structs are supported: `s := packed struct { item: u32 }`. Packed layout guarantees no padding between fields (C-compatible, dense bit layout).
  - Field defaults: struct fields may have default values: `s := struct { x: i32 = 0, name: []u8 = "default" }`. A `.{}` zero-initialisation uses field defaults where present.
  - Instantiation:
    - Named fields: `s{ item: 1 }` or `.{ item: 1 }` (dot-inferred when the type can be determined from context).
    - Positional (tuple-style): `{1}` — equivalent to `.{}` with positional fields.
  - If an expression evaluates to a struct type, you can immediately construct an instance: `get_type(){}` calls `get_type()`, which returns a `type`, and `{}` constructs a zero-value instance of that struct type.
- Type Aliases: Assigning a type expression to a name creates a transparent alias — the two names are interchangeable and refer to the exact same type. Generic instantiation is memoized: calling `List(i32)` twice returns the same type object.
  - Example: `IntList := List(i32)` — `IntList` IS `List(i32)`. Passing an `IntList` where `List(i32)` is expected is always valid.
  - To create a distinct named type (newtype), wrap it: `Meters := struct { value: f32 }`.
- Enums (Sum Types / Tagged Unions): Can hold complex payloads.
  - Definition: `r := enum { variant1, variant2: i32 }`.
  - Explicit representation type is supported with unsigned integer widths: `r := enum(u8) { A, B }`.
  - Instantiation: `r.variant2(5)` or `.variant2(5)` if the root enum can be determined from context.

## 6. CONTROL FLOW (EVERYTHING IS AN EXPRESSION)
### Universal Body Syntax (If/Else, Match, Loops, even defer)
- Curly braces are OPTIONAL for a single expression or single statement, but required for multi-statement blocks.
- Note on "void" expressions: a single statement (like an assignment `a = 1`, a void function call, a for loop, or keywords like `break`) is treated as a valid single expression returning `void`.
  - Example: `if condition do_thing() else a = 2`

### If/Else
- When used as a **statement**, any body form is valid:
  ```
  if condition { do_thing(); a = 1 }
  if condition do_thing()
  if condition {} else {}
  ```
- When used as an **expression** (the result is bound or used), ALL branches must produce a non-void value of the same type, and ALL branches are required:
  - Bare expression branches: `v := if cond value else other_value` — preferred form.
  - Block branches must use `break` to produce a value: `v := if cond { break compute() } else { break 0 }`.
  - Mixing bare and block forms in the same expression is not allowed.
  - Invalid: `v := if cond { value } else other_value` — cannot wrap a bare expression in braces in expression context.
- Null/Optional Unification: If one branch is a concrete type and another is `null`, the expression type is unified to `?T`.
  - Example: `w := match total { 1: 1, _: null }` — `w` is inferred as `?i32`.
- Safe optional unwrap: `if n: |v| {}` — executes only if `n` is non-null, binding the inner value to `v`. Discard with `if n: |_| {}`.

### Match
- `match total { 0..1: body, _: body }`.
- Enum unwrapping: `match res { .variant2: |val| body }`.
- Must be exhaustive. A `_: body` catch-all is only required if the match is not already exhaustive over all variants/cases.
- Branch Type Matching: All branches must evaluate to the same type. Null/Optional unification applies.

### Loops (`for`)
- All forms use the `for` keyword:
  - Range (exclusive): `for 0..10: |v| body`
  - Range (inclusive): `for 0..=10: |v| body`
  - Array/slice iteration: `for arr: |v| body` — iterates all arrays and slices; `v` receives each element.
  - While-style (bool condition): `for total < 10: body` — repeats while the condition is true.
  - Infinite: `for { body }` — loop until explicit `break`.
- The loop variable binding `|v|` is optional for while-style and infinite loops.

### Blocks & Break/Continue
- Blocks can be labeled (`blk: { ... }`) and broken out of with `break :blk` or `break :blk value`.
- `continue :blk` targets the labeled loop.
- A block broken with a value has that value's type; a block that falls through or breaks without a value is `void`.

## 7. ERROR HANDLING
- Errorable Functions: Return types appended with `!` followed by a comma-separated list of error enums (e.g., `f32!DivideError1,DivideError2`).
  - **Inferred error set**: Writing `!` alone (e.g., `f32!` or `!`) tells the compiler to infer the complete error set from all `!`-propagating expressions in the body. The declaration is still required; the compiler fills in the set.
- Handling Errors:
  - Default value fallback: `A := divide(1,0) or 0`
  - Catch block: `C := divide(1,0) or { break 0 }` — `break` provides the fallback value.
  - Catch with error capture: `D := divide(1,0) or |err| { break 0 }` — `err` is the inferred error type; must `break` with a value if the result is bound.
  - Void fallback via control flow: `do_thing() or return` / `do_thing() or break` / `do_thing() or continue` — the `or` fallback is allowed to be void if it exits the current scope via a control-flow statement. No `break value` is required in this case.
  - Force Unwrap / Propagation: `divide(1,1).!`
    - In non-errorable functions, `.!` traps (panics) on error.
    - In errorable functions, `.!` propagates the error to the caller.
    - If the error set is explicit, propagated errors must be covered by the declared set. If the set is inferred (`!`), the compiler expands it automatically.

## 8. OPTIONAL HANDLING
- Force unwrap: `n.?` — traps if null.
- Fallback/Default: `n or 1` or `n or { break 1 }` — the `or` keyword handles both optionals and errorable types; the compiler resolves which based on the LHS type.
- Void fallback via control flow: `n or return` — same as §7; allowed when the fallback exits the scope.
- Safe if-unwrapping: `if n: |v| {}` — see §6.
- Combined optional + errorable (`?T!E`): `or` applies **outside-in** — the outermost wrapper is handled first. For `?T!E`, the `!E` layer is outermost, so `or` addresses the error case first. After the error is handled (e.g. via `.!`), a second `or` addresses the `?T` case.
  - Example: `func().! or 1` — `.!` propagates/traps the error, then `or 1` unwraps the optional.
  - You cannot use `.?` before handling the `!E` layer.

## 9. COMPILE-TIME (COMPTIME) & METAPROGRAMMING
- Types are First-Class: Generics are achieved by passing `type` as a function argument (e.g., `List := (T: type) type => struct {}`).
- **Comptime parameters** (`comp`): A parameter annotated with `comp` must receive a compile-time-known argument. The compiler detects non-comptime arguments and emits a compile error.
  - `(T: comp type)` — T must be a compile-time-known type (enables monomorphisation).
  - `(n: comp i32)` — n must be a compile-time-known integer.
  - Comptime-known values include: type literals, integer/float/bool/string literals, and expressions wrapped in `comp`.
  - If a non-comptime value is passed to a `comp` parameter, the compiler emits an error at the call site.
- Any expression that evaluates to a `type` is valid as a parameter type annotation. This includes `comp` expressions, function calls, and conditionals:
  - `(T: type)` — T is a runtime type argument.
  - `(T: comp type)` — T must be a compile-time-known type.
  - `(x: get_my_type())` — the type annotation is the result of calling `get_my_type()` at compile time.
- Comptime Evaluation: Prefixing an expression with `comp` forces compile-time execution (`pi := comp calc_pi()`). If evaluation fails, compilation fails (no runtime fallback).
- Inline Execution: Supported inline forms are `inline for <range>`, direct inline calls, and inline function literals.
  - `inline for` requires compile-time-evaluable range bounds and unrolls the loop body. Calling non-inline functions from inside an inline for body is permitted (they execute normally). Calling an inline function from inside pastes that function's body at the call site. `break` is not allowed inside `inline for`.
  - Inline calls paste the function body at the call site; if inlining is impossible, compilation fails.
- `$self()` refers to the type currently being instantiated (valid inside struct/type definitions).

## 10. DEFER
- Executes block at the end of the current scope in LIFO order (last in, first out).
- Syntax: `defer { ... }`.
- Error-only defer: `defer |e| { ... }` — executes *only* if the scope exits via an error.
  - `e` is the inferred error type. To explicitly annotate it: `defer |e: MyError| { ... }`.

## 11. COMMENTS & DOCUMENTATION
- Line Comments: `// comment` (ignored during lexing).
- Block Comments: `/* comment */` (ignored during lexing).
- Doc Comments: `/// comment` (the lexer MUST capture these as `DOC_COMMENT` tokens so the parser can attach them to the next declaration).

## 12. COMPILER BUILT-INS (INTRINSICS)
- Prefix: All built-in compiler functions are prefixed with `$`. The lexer tokenizes `$word` as a `BUILTIN_IDENTIFIER`.
- Core Built-ins:
  - Casting: `$as(Type, value)` — converts value to Type. The source value must be a runtime-known variable or expression; the target `Type` must be a valid type name. Any numeric type can be cast to any other numeric type (`f32` ↔ `i32`, etc.). Pointer casts (`$as(*i32, *u8)`, `$as(*T, *any)`) are permitted. Casting an integer to a pointer or vice versa is also permitted (`$as(u64, ptr)`).
  - Type Info: `$typeof(expr)` — returns the type of the expression as a `type` value.
  - Self-reference: `$self()` — inside a struct/type definition, refers to the type being defined.
  - Memory: `$sizeof(Type)`, `$alignof(Type)`, `$offsetof(Type, field_name)`.
  - State: `$unreachable()` — marks a code path that must never execute.
  - Comptime: `$compile_error("msg")` — triggers a user-defined compile error.
  - Runtime: `$panic("msg")` — panics at runtime with the given message.
- Std-owned I/O: Printing is provided by imported modules, not by compiler-recognized globals.
  - Example: `io := use "std/io"` then `io.println("Hello, world")`.
  - `print(...)` / `println(...)` are unresolved unless user code defines or imports them explicitly.

## 13. MEMORY & ALLOCATORS
- Stack allocation happens automatically for local variables.
- Heap allocation requires an explicit allocator. The standard allocator interface is:
  ```dyn
  Allocator := struct {
      ctx:   *any,
      alloc: fn(ctx: *any, size: usize, align: usize) ?*any,
      free:  fn(ctx: *any, ptr: *any, size: usize) void,
  }
  ```
- Specific allocator implementations (arena, page, libc, etc.) are provided by `std` modules and satisfy this interface via the `*any` context pointer.
- There are no built-in `new`/`delete` keywords; all heap allocation goes through an `Allocator` value.
