> Historical compiler implementation brief. Current behavior is defined by
> docs/language.md, docs/memory.md and docs/release/readiness.md. For writing Dyn
> applications, start with docs/agent-guide.md; do not treat aspirational features
> below as implemented compiler behavior.

You are implementing the Dyn programming language compiler.

Your task is to build a working compiler incrementally, not merely describe one.
You must produce source files, build files, tests, documentation, and commands
that can be executed locally.

Do not invent language features. If a behavior is unspecified, record it as an
explicit TODO or compiler diagnostic instead of silently choosing semantics.

===============================================================================
1. LANGUAGE IDENTITY
===============================================================================

Dyn is a small, explicit, native systems-programming language.

Its goals are:
- simple syntax;
- easy readability;
- fast compilation and execution;
- explicit allocation and resource management;
- no garbage collection;
- no hidden allocation;
- no hidden runtime dispatch;
- no object-oriented programming requirement;
- no conventional generic system;
- no interfaces or vtables;
- no universal any type;
- no pointer arithmetic;
- data-oriented and procedural programming;
- arenas, pools, explicit resources, and ordinary functions.

The language core must remain small. Functionality that can be implemented in
the standard library must not be added to the language.

===============================================================================
2. IMPLEMENTATION AND BOOTSTRAP STRATEGY
===============================================================================

The bootstrap compiler is written in C.

The compiler executable is named:
  dyn

The build system is just; root justfile delegates to component justfiles.

The compiler must eventually be rewritten in Dyn and become self-hosting.
The initial C compiler exists only to bootstrap the Dyn implementation.

The initial compiler backend must not emit C.

Use this pipeline:
    Dyn source
      -> Tree-sitter parse tree
      -> compiler-owned AST
      -> module graph
      -> name resolution
      -> type checking
      -> typed Dyn IR
      -> LLVM IR
      -> native object file
      -> linker
      -> executable

Use LLVM initially through an appropriate C-compatible interface.

Use LLVM target support for:
- Linux x86-64;
- Windows x86-64;
- macOS ARM64.

Use LLVM object-file generation and lld where possible. Do not require users
to install MSVC. Do not require users to install a platform vendor compiler
where LLVM and lld can provide the necessary functionality.

Platform SDK and system-library requirements that cannot reasonably be removed
must be documented and isolated.

The compiler should eventually support:
    dyn build <path>
    dyn run <path>
    dyn check <path>
    dyn test
    dyn fmt <path>
    dyn clean
    dyn version
    dyn help

Suggested build options:
    --target
    --debug
    --release
    --output
    --emit-ir
    --emit-object
    --emit-asm
    --no-link

===============================================================================
3. PROJECT STRUCTURE
===============================================================================

Use a clear C project layout, with support for unity builds, for example:

    justfile
    include/
    src/
      main.c
      cli/
      source/
      module/
      ast/
      type/
      sema/
      ir/
      codegen/
      diagnostics/
      runtime/
    tests/
    examples/
    grammar.js
    docs/

Use explicit compiler-owned data structures.

The compiler should itself use explicit arenas and data structures where
practical. Avoid hidden allocations in the compiler implementation.

Create separate modules for:
- source files and source spans;
- command-line handling;
- module loading;
- Tree-sitter integration;
- AST construction;
- symbol tables;
- type interning;
- layout computation;
- semantic analysis;
- diagnostics;
- typed IR;
- LLVM lowering;
- executable linking;
- testing.

===============================================================================
4. TREE-SITTER GRAMMAR
===============================================================================

The supplied Tree-sitter grammar is a syntax starting point.

Do not assume the grammar completely defines language semantics.

The compiler must:
1. parse using Tree-sitter;
2. preserve source locations;
3. convert Tree-sitter nodes into a compiler-owned AST;
4. perform semantic analysis separately.

Update the grammar where required by the language specification.

Do not use Tree-sitter nodes as the compiler's long-term semantic representation.

The grammar must eventually support:
- module imports;
- optional public declarations;
- constants;
- mutable globals;
- structs;
- packed structs;
- enums;
- functions;
- local declarations;
- assignments;
- arrays;
- slices;
- pointers;
- function pointers;
- blocks;
- if/else;
- for loops;
- labeled break and continue;
- case statements;
- enum payload matching;
- defer;
- compiler intrinsics;
- array and slice indexing;
- array and slice ranges;
- `for item in items`;
- `for *item in items`;
- `for *const item in items`.

There are no generic or parameterized structs/enums/functions.

Do not add:
- `<T>` syntax;
- `[T]` generic syntax;
- `$T` generic syntax;
- `T: type`;
- type-valued parameters;
- interfaces;
- vtables;
- methods;
- closures;
- first-class type values.

===============================================================================
5. MODULES AND IMPORTS
===============================================================================

Imports use this syntax:
    `use "std/io"`
    `use "std/io" log`

The identifier after the path is an optional alias. There is no `as` keyword.

Without an alias, the module is used under its module name:
```
    use "std/io"
    io.println(...)
```

With an alias:
```
    use "std/io" log
    log.println(...)
```

Modules are directories.

Module paths resolve relative to the current module or project root according to
the project configuration.

Imports are processed before semantic analysis.

Import cycles are errors.

The module loader must track an import stack and report the full cycle:
    cyclic import:
      main -> graphics -> math -> graphics

Declarations are visible independently of source order.

`pub` makes a declaration accessible to importing modules.

Unqualified imported names are allowed only if the language/module resolver
explicitly supports them; otherwise prefer module-qualified access. Do not
silently import names into the local namespace without implementing a clear
collision policy.

Blocks introduce scopes.

Local structs, enums, functions, and type aliases are not allowed initially.

Local variables are allowed.

Shadowing is forbidden.

===============================================================================
6. DECLARATIONS
===============================================================================

Supported declarations include:
    use
    const
    mutable global variables
    struct
    packed struct
    enum
    fn
    type alias

Public declarations use:
```
    pub struct Point { ... }
    pub fn main() { ... }
```

The compiler must reject duplicate declarations in one namespace.

Names are case-sensitive.

The current language uses ordinary variable declarations for globals:
    `global_log: Logger`

No `global` keyword is required.

Mutable globals are allowed.

Globals may have runtime initializers.

Runtime global initialization must be implemented similarly to Go:
1. imported modules initialize before importing modules;
2. global initialization dependencies are respected;
3. initialization happens once;
4. initialization occurs before `main`;
5. global initialization is single-threaded;
6. initialization cycles are rejected;
7. initialization failures panic;
8. user-created threads begin only after program initialization.

Generate internal initialization functions as needed:
    __dyn_init_<module>

Do not generate initialization functions for modules with no runtime
initialization work.

Constants cannot call functions.

Constants may use compiler-evaluable expressions involving:
- literals;
- other constants;
- supported operators;
- sizeof;
- alignof;
- other explicitly supported compile-time operations.

Do not add general compile-time execution, compile-time blocks, macros, compile-time
I/O, or compile-time allocation.

===============================================================================
7. TYPES
===============================================================================

Primitive types:
    i8
    i16
    i32
    i64
    u8
    u16
    u32
    u64
    isize
    usize
    f32
    f64
    bool
    void

There is no builtin string type.

There is no builtin rune type.

String literals are null-terminated byte data and are immutable.

The exact slice/count treatment of the trailing null byte must be represented
consistently by the compiler and standard library.

Integer literals default to i32.

Floating-point literals default to f32.

Literals may adapt to an expected numeric type when representable.

Implicit numeric conversions are allowed only when no information can be lost.

Mixed numeric variables are not implicitly combined:

    i32_value + u32_value

is a type error unless explicitly converted.

The absence of a function return type means void:
```
    fn print() {
      ...
    }
```

is equivalent to a void-returning function.

`void` is not a normal value type.

===============================================================================
8. POINTERS
===============================================================================

Pointer syntax:
```
    *T
    *const T
```

Pointers are thin native pointers.

There is no pointer arithmetic.

These are invalid:
    p + 1
    (p + 1).*

Use arrays and slices for checked traversal.

`*void` is the raw pointer type.

Pointers can be compared by address.

Pointer comparison with nil is valid.

Nil is valid for pointer types.

Function pointers are explicit:
    `*fn(i32, i32) i32`

Taking a function address requires `&`:
    `&math_add`

Passing a function name without `&` is invalid.

Pointer dereference syntax is:
    `p.*`

Field access automatically dereferences pointers:
    `p.x`

is equivalent to:
    `p.*.x`

Pointer dereference itself is not generally bounds-checked.

Raw pointer casts are explicit and potentially unsafe.

===============================================================================
9. CONST POINTERS AND SLICES
===============================================================================

`*const T` is shallow const.

Through `*const T`:
- the pointed-to object cannot be modified;
- pointer-valued fields cannot be reassigned;
- if a pointer-valued field points to mutable data, that pointed-to data remains
  mutable through the nested pointer.

Example:
```
    struct Outer {
      value: i32
      child: *Inner
    }

    p: *const Outer

    p.value = 1       // error
    p.child = nil     // error
    p.child.value = 1 // allowed if child points to mutable Inner
```
Const slices use:
    `[]const T`

Slices are non-owning views containing:
    data pointer + count

Slices are mutable by default:
    `[]T`

Slices are not directly comparable.

Slice equality must be implemented by an explicit library function.

A zero-value slice has:
    data = nil
    count = 0

===============================================================================
10. ARRAYS AND SLICES
===============================================================================

Fixed array types:
    `[N]T`

Array literals:
    `[1, 2, 3]`

The compiler infers the length and element type:
    `values := [1, 2, 3]`

has type:
    `[3]i32`

An empty array literal is used for zero initialization when the expected type
is known:
    `values: [3]i32 = []`

This is invalid:
    `values := []`

because no type or length can be inferred.

Arrays are copied by value.

Array and slice indexing is bounds-checked.

Array-to-slice conversion is allowed:
```
    values: [3]i32
    view: []i32 = values[..]
```

Slice syntax:
```
    values[..]
    values[1..4]
    values[1..]
    values[..4]
```

Use exclusive upper bounds.

The compiler must define whether slice ranges produce nil or empty slices for
zero-length ranges. Prefer:
    data = original pointer plus offset
    count = 0

unless the range is derived from a nil slice, in which case preserve nil if
the implementation needs that distinction.

===============================================================================
11. STRUCTS
===============================================================================

Struct syntax:
```
    struct Point {
      x: f32,
      y: f32,
    }
```

Multiple fields may share a type:
```
    struct Point {
      x, y: f32,
    }
```

Field defaults are allowed:
```
    struct Counter {
      n: i32 = 0,
    }
```

Omitted fields are zero-initialized and field defaults are applied according
to a clearly documented ordering rule.

Unknown fields are errors.

Duplicate fields are errors.

Field order determines layout.

Structs are copied by value.

Packed structs are supported:
```
    packed struct Header {
      tag: u8,
      length: u32,
    }
```

Packed layout must follow conventional packed-struct behavior:
- declaration order is preserved;
- inter-field alignment padding is removed;
- packed struct alignment is 1 unless the target ABI requires an explicit
  documented exception;
- exact field offsets are calculated by the layout engine;
- `sizeof` and `alignof` expose the result;
- direct field access supports potentially unaligned fields;
- taking addresses of packed fields is allowed;
- dereferencing an unaligned pointer may be unsafe or target-dependent.

Structs cannot contain themselves by value.

Recursive structs must use pointers or slices:
```
    struct Node {
      next: *Node,
    }
```

===============================================================================
12. ENUMS
===============================================================================

Plain enums:
```
    enum MyEnum {
      Some,
      Thing,
      Here,
    }
```

Payload enums are tagged unions:
```
    enum Partnered {
      Some: i32,
      Thing: ThingPayload,
      Here: f32,
    }
```

The backing tag type may be specified:
```
    enum(i8) Error {
      None,
      Invalid,
    }
```

Explicit discriminant values are not initially supported.

Enum payload variants are constructed with call syntax:
```
    Partnered.Some(42)
    Partnered.Thing(ThingPayload{ info: 1 })
    Partnered.Here(2.0)
```

The compiler must calculate tagged-union layout:
- tag;
- payload storage sized for the largest payload;
- alignment;
- padding;
- total size.

Payload variants may contain structs, pointers, arrays, and slices.

Enums without payloads can be compared.

Payload enum equality must be explicitly defined by the type checker. Do not
silently perform deep pointer-following equality.

Enum-to-integer conversion is not implicit.

Exhaustive enum matching is required unless `_` is present.

===============================================================================
13. VARIABLES AND ASSIGNMENT
===============================================================================

Variables are zero-initialized.

These are valid:
```
    x: i32
    x: i32 = 10
    x := 10
```

Reading an uninitialized declaration is safe because it is zero-initialized.
  `:=` performs local type inference.
  `=` performs assignment.

Compound assignments are supported:
    +=
    -=
    *=
    /=
    %=
    &=
    |=
    >>=
    <<=
    ~=
    ^=

Increment and decrement operators are not supported.

Declarations are statements.

Parameters and locals are mutable unless constness prevents modification.

All variables are potentially shareable across threads.

Sharing does not provide synchronization.

The compiler does not perform race analysis initially.

===============================================================================
14. THREADING AND SYNCHRONIZATION
===============================================================================

Threading facilities belong in the standard library, especially `std/thread`.

Do not add mutexes, atomics, or synchronization as special language-level
types.

The standard library should provide ordinary values and functions for:
- thread creation;
- thread joining;
- mutexes;
- atomics;
- condition variables if needed;
- thread-local storage if implemented;
- synchronization primitives.

All variables are shareable by default.

Unsynchronized concurrent access is legal from the type system's perspective
but may be a data race.

A future synchronization wrapper may be a standard-library type rather than a
language keyword.

Do not add `sync` syntax until its exact semantics are defined.

Thread-local storage may be implemented through a standard-library or runtime
facility. If the `thread_local` keyword is retained, define it separately from
shared synchronization.

===============================================================================
15. FUNCTIONS AND FUNCTION POINTERS
===============================================================================

Function syntax:
```
    fn add(x: i32, y: i32) i32 {
      return x + y
    }
```

No return type means void:
```
    fn work() {
      ...
    }
```

Function pointer syntax:
    `*fn(i32, i32) i32`

Function addresses require:
    `&add`

Function pointers may be stored in structs:
```
    struct Interface {
      cool_fn: *fn(i32, i32) i32,
    }

    const interface := Interface{
      cool_fn: &math_add,
    }
```

Calling a function pointer:
    `interface.cool_fn(1, 2)`

No methods are supported.

No closures are supported initially.

===============================================================================
16. CONTROL FLOW
===============================================================================

Conditions must have type bool.

Supported:
```
    if condition {} else {}
    for {}
    for condition {}
    for item in array_or_slice {}
    for *item in array_or_slice {}
    for *const item in array_or_slice {}
```

Loop iteration rules:
```
    for item in items {
      // item is a copy of element type T
    }

    for *item in items {
      // item is *T and may mutate the element
    }

    for *const item in items {
      // item is *const T
    }
```

The loop variable is scoped to the loop body.

`break` and `continue` are valid only within loops.

Labeled loops are supported:
```
    outer: for {
      break: outer
    }
```

Functions with non-void return types must return on every reachable path.

Unreachable statements produce warnings.

===============================================================================
17. CASE STATEMENTS
===============================================================================

Case syntax:
```
    case value {
      1 => { ... },
      2..=99 => { ... },
      101, 102 => { ... },
      _ => { ... },
    }
```

Ranges use inclusive or exclusive upper bounds:
    `1..10`
    `1..=10`

Case arms are comma-separated.

Duplicate values are errors.

Overlapping ranges are errors.

Enum matching is supported:
```
    case value {
      MyEnum.Some => { ... },
      MyEnum.Thing => { ... },
      MyEnum.Here => { ... },
    }
```

Payload binding is supported:
```
    case value {
      Partnered.Thing payload => {
        ...
      },
      _ => {},
    }
```

Nested destructuring is not supported.

Exhaustiveness is checked for finite enums unless `_` is present.

===============================================================================
18. OPERATORS
===============================================================================

Logical:
    ||
    &&

Equality:
    ==
    !=

Relational:
    >
    <
    >=
    <=

Bitwise:
    |
    ^
    &
    <<
    >>

Arithmetic:
    +
    -
    *
    /
    %

Arithmetic overflow is checked.

Wrapping arithmetic operators are not supported.

Division by zero is a runtime panic.

If compile-time evaluation proves division by zero or another invalid constant
operation, report a compile-time error.

Constant invalid shifts must be compile-time errors.

Runtime invalid shifts must follow the defined C-like behavior, but Dyn must
not inherit undefined behavior silently. Use a documented checked rule for
invalid shift counts.

Mixed numeric types are errors unless explicitly cast.

Boolean logical operations are short-circuiting.

Boolean bitwise operations are permitted:
    `true & false`
    `true | false`
    `true ^ false`

===============================================================================
19. CASTING
===============================================================================

Numeric/type conversion:
    `#cast(u8) value`

Representation reinterpretation:
    `#bitcast(f32) value`

`#cast` may lose data when narrowing.

If compile-time analysis proves loss is possible, emit a warning and suggest
using a wider type or reevaluating the representation.

If a constant conversion is definitely invalid, report a compile-time error.

`#bitcast` requires compatible representation sizes and layouts.

Do not silently insert casts.

===============================================================================
20. BUILTINS
===============================================================================

Builtins are compiler-recognized operations rather than ordinary runtime
functions.

Required builtins:
```
    #sizeof(type_or_expression)
    #alignof(type_or_expression)
    #len(value)
    #typeof(value)
    #cast(type) value
    #bitcast(type) value
    #panic("message")
    #syscall(...)
```

`#sizeof` and `#alignof` return usize.

`#len` accepts a value:
```
    #len(bytes)
    #len(array)
    #len(slice)
```

`#typeof(value)` returns runtime reflection metadata:
    TypeInfo

Only types used with reflection need generated metadata.

Do not add general compile-time reflection or compile-time code execution.

===============================================================================
21. RUNTIME REFLECTION
===============================================================================

Reflection is primarily a standard-library facility.

Use:
    `use "std/reflect"`

The compiler provides `#typeof`.

The standard library defines types such as:
```
    enum Kind {
      Invalid,
      Void,
      Bool,
      Integer,
      Float,
      Pointer,
      Array,
      Slice,
      Struct,
      Enum,
      Function,
    }

    struct TypeInfo {
      id: u64,
      kind: Kind,
      name: []const u8,
      size: usize,
      alignment: usize,
    }
```

`#typeof(value)` returns `TypeInfo`.

Only reflected types require emitted metadata.

The metadata may later be expanded with:
- struct fields;
- enum variants;
- element types;
- pointer target types;
- function arguments;
- return types.

Do not make types first-class runtime values.

Do not add a universal `any` type.

A reflected value may be represented explicitly:
```
    struct Value {
      type: *const TypeInfo,
      data: *const void,
    }
```

This is a normal concrete structure, not an interface or vtable.

Function signature metadata may expose declared arguments:
    `#typeof(function_name).arguments`

This describes parameter metadata, not actual values.

===============================================================================
22. EXPLICIT REFLECTION ARGUMENTS
===============================================================================

Do not add `...any`.

Do not add hidden variadic argument arrays.

Formatting and generic runtime argument handling should use explicit:
    `[]reflect.Argument`

Possible structure:
```
    struct Argument {
      type: *const TypeInfo,
      data: *const void,
    }
```

A function can accept:
    `fn println(format: []const u8, args: []reflect.Argument) void`

The programmer may use reflection utilities to inspect arguments.

There is no variadic declaration syntax in the language.

Any argument construction must be explicit or provided by ordinary standard-library
helpers that do not introduce hidden allocation.

If convenient construction cannot be implemented safely as an ordinary function,
do not invent hidden compiler behavior. Use an explicit builder API or postpone
the convenience feature.

===============================================================================
23. DEFER
===============================================================================

Defer executes at the end of the enclosing block.

Defer is LIFO.

Arguments to deferred calls are evaluated at the defer statement:
    `defer file_close(&file)`

The call is executed later, but the function and arguments are captured at the
defer site.

Deferred blocks may capture local variables:
```
    defer {
      cleanup(resource)
    }
```

Defers run during panic unwinding.

Panic unwinds the whole call stack.

There is no recover mechanism initially.

Unrecovered panic terminates the process.

Lower defer into explicit cleanup control flow in the IR. Do not require a large
exception runtime initially.

===============================================================================
24. MEMORY AND RESOURCE MANAGEMENT
===============================================================================

There is no garbage collector.

Pointers are non-owning.

Slices are non-owning.

Arenas are the primary bulk-allocation mechanism.

Pools/free lists are for individually reusable objects.

External resources require explicit cleanup.

Ordinary arena allocations do not run destructors.

Arenas are fixed-capacity with a hard limit.

Arenas may be chained manually.

Arena allocation is zero-initialized.

Arena exhaustion panics by default.

Arena marks and rewinds follow the selected arena model:

    mark := mem.arena_mark(&arena)
    mem.arena_rewind(&arena, mark)

Arena behavior must document:
- reset;
- release;
- marks;
- rewind;
- invalidation;
- nested marks;
- capacity;
- alignment;
- zero initialization;
- thread confinement.

Raw allocation can use:
    `raw := mem.arena_push(&arena, #sizeof(Point), #alignof(Point))`

Then explicitly cast:
    `point: *Point = #cast(*Point) raw`

Do not require typed allocation or type-valued function arguments.

===============================================================================
25. STANDARD LIBRARY
===============================================================================

The standard library should contain:
    std/io
    std/os
    std/mem
    std/thread
    std/reflect

It may later contain:
    std/collections
    std/strings
    std/math
    std/time
    std/test
    std/path
    std/process
    std/net
    std/hash

The language should not contain special collection types beyond arrays and
slices.

Use explicit collection types in the standard library:
    List
    ChunkedList
    LinkedList
    Map
    Pool

Collections must document:
- allocator ownership;
- pointer stability;
- invalidation rules;
- removal behavior;
- growth behavior;
- reset behavior.

Formatting belongs in the standard library and should use explicit reflection
arguments if generic formatting is provided.

===============================================================================
26. RUNTIME
===============================================================================

The runtime must be minimal.

A basic program should not link thread, reflection, formatting, or file-system
support unless used.

Split runtime components conceptually into:
    dynrt_core
    dynrt_mem
    dynrt_thread
    dynrt_os
    dynrt_reflect
    dynrt_format

The core runtime should contain only what every program needs:
- entry point;
- process exit;
- panic termination;
- minimal compiler helpers;
- global initialization dispatch.

The compiler should emit ordinary operations inline where possible:
- arithmetic checks;
- bounds checks;
- array copying;
- struct copying;
- slice construction;
- field access.

The initial runtime may use small platform-specific bootstrap code. The long-term
runtime should be written mostly in Dyn.

The runtime must not include:
- garbage collection;
- mandatory scheduler;
- mandatory reflection;
- mandatory formatting;
- universal dynamic values;
- automatic destructor traversal;
- hidden heap allocation.

===============================================================================
27. DIAGNOSTICS
===============================================================================

Diagnostics must include:
- severity;
- file;
- line;
- column;
- source span;
- message;
- notes;
- related spans where useful.

Support:
- errors;
- warnings;
- configurable warning levels;
- warnings-as-errors;
- unreachable-code warnings;
- lossy-cast warnings;
- unused-variable warnings;
- unused-import warnings;
- resource-cleanup warnings where statically known.

Examples of diagnostics:
    error: cyclic import detected
    error: assignment through *const pointer
    error: duplicate case value
    error: non-exhaustive enum case
    error: invalid array index
    error: invalid constant division by zero
    warning: conversion from i64 to u8 may lose data

Never silently invent semantics for unsupported constructs.

===============================================================================
28. IR
===============================================================================

Create a typed intermediate representation with explicit types.

The IR must represent:
- constants;
- locals;
- globals;
- loads;
- stores;
- pointer address operations;
- fields;
- array indexing;
- slice indexing;
- calls;
- indirect calls;
- checked arithmetic;
- comparisons;
- branches;
- switch/case;
- loops;
- defer cleanup;
- panic paths;
- module initialization;
- reflection metadata references.

Use basic blocks and explicit control-flow edges.

Lower:
- checked arithmetic into overflow checks and panic branches;
- bounds checks into comparison and panic branches;
- defer into cleanup blocks;
- global initialization into module initialization functions.

===============================================================================
29. LLVM BACKEND
===============================================================================

Lower the typed Dyn IR to LLVM IR.

Mappings:
    i8/i16/i32/i64 -> LLVM integer widths
    u8/u16/u32/u64 -> LLVM integer widths
    isize/usize    -> target pointer width
    f32/f64        -> LLVM floating types
    bool            -> LLVM i1
    pointers        -> thin LLVM pointers
    slices          -> LLVM structs containing pointer and usize
    arrays          -> LLVM arrays
    structs         -> LLVM structs
    enums           -> tag plus payload storage

Use LLVM overflow intrinsics or equivalent logic for checked arithmetic.

Emit object files using LLVM target support.

Link using lld or the best available platform-native linker integration.

Do not emit C.

===============================================================================
30. TESTING
===============================================================================

Every feature must have:
- parser tests;
- AST tests where useful;
- semantic-error tests;
- code-generation tests;
- runtime tests;
- diagnostic tests.

Test categories:
    tests/parser/
    tests/typecheck/
    tests/codegen/
    tests/runtime/
    tests/modules/
    tests/diagnostics/
    tests/stdlib/

Begin with:
    `fn main() {}`

Then add:
- literals;
- locals;
- assignment;
- arithmetic;
- if;
- functions;
- structs;
- pointers;
- arrays;
- slices;
- enums;
- case;
- modules;
- globals;
- runtime global initialization;
- defer;
- function pointers;
- reflection;
- arenas;
- threading;
- full demo.

The provided demo program must eventually compile and run.

After the demo works, begin compiling the Dyn compiler written in Dyn.

===============================================================================
31. DEVELOPMENT ORDER
===============================================================================

Implement in this order:
1. Project build and CLI.
2. Source manager and diagnostics.
3. Tree-sitter parser integration.
4. Compiler-owned AST.
5. Minimal function/main compilation.
6. Primitive types and expressions.
7. Locals and assignment.
8. Control flow.
9. Structs and layout.
10. Pointers and const pointers.
11. Arrays and slices.
12. Enums and case.
13. Modules and imports.
14. Globals and initialization.
15. Function pointers.
16. Defer and panic paths.
17. Builtins.
18. LLVM object generation.
19. Linking and executable output.
20. Standard-library ABI.
21. Reflection metadata.
22. Runtime and standard-library implementation.
23. Complete demo.
24. Bootstrap compiler written in Dyn.

At every stage:
- keep the project compiling;
- add tests;
- avoid speculative features;
- update documentation;
- report unsupported language behavior explicitly.

===============================================================================
32. IMPORTANT RESTRICTIONS
===============================================================================

Do not add:
- garbage collection;
- ownership or borrow checking;
- Rust-like lifetime inference;
- interfaces;
- vtables;
- methods;
- closures;
- generics;
- type parameters;
- first-class type values;
- universal any;
- hidden heap allocation;
- pointer arithmetic;
- implicit resource destruction;
- C source generation;
- compiler magic for ordinary library behavior unless explicitly specified.

When a feature is needed by the standard library, first attempt to implement it
as ordinary Dyn code. Add a compiler builtin only if ordinary Dyn code cannot
express it.

===============================================================================
33. FIRST REQUIRED DELIVERABLE
===============================================================================

Before implementing the entire compiler, produce:
1. A repository layout.
2. A justfile.
3. A compiler architecture document. - nothing too complicated here, just generics and nothing overengineered, sticking with data oriented
4. A language-semantics document.
5. A corrected Tree-sitter grammar.
6. A minimal C compiler executable.
7. A working `dyn check`.
8. A working `dyn build`.
9. A test compiling and running:
    `fn main() {}`

10. A tracked list of unresolved decisions.

Do not pretend that later features are implemented. Clearly mark each milestone.

The final goal is a native Dyn compiler whose compiler implementation can itself
be rewritten in Dyn, while keeping the language core compact and moving most
functionality into the standard library.

Current project structure:
  compiler/ - the compiler
  example/ - me messing with syntax so dont worry too much about it for now
  tree-sitter-dyn/ - tree sitter grammar, includes syntax highlighting and the like for neovim and helix
  zed-dyn/ - my zed highlighting for dyn

Most importantly, I want you to teach me how youre making it because I want to learn, I want to become an expert in not only writing compilers but writing good code through this, how to approach the problem etc
