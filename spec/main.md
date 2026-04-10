# Dyn Language Specification v0.1

## Status
- This specification is intended to be sufficient for implementing a compiler frontend and core semantic analysis for Dyn.
- “Normative” means required behavior.
- “Provisional” means intended behavior not yet fully locked.
- “Omitted” means not part of v0.1 and should not be implemented unless separately specified.

# 0. Design goals
Dyn is an ahead-of-time compiled systems programming language with:
- explicit mutability
- static typing
- allocator-based memory management
- compile-time execution and type-level programming
- practical reference alias checking lighter than a full borrow checker
- expression-oriented control flow where useful

Dyn is intentionally in the design space of C/Zig/Rust, with strong Zig influence.

# 1. Source files and modules

## 1.1 Source file structure

Normative:
A source file consists of:
- one module declaration
- zero or more top-level declarations

Grammar:
```text
SourceFile := ModuleDecl TopLevelDecl*
ModuleDecl := 'module' Identifier
```

Example:
```dyn
module main
os := use "std/os"
main := () {}
```

## 1.2 Top-level restrictions

Normative:
Only declarations are allowed at top level.
Top-level executable statements are invalid.

Valid:
```dyn
module main
x := 1
Point := struct {}
main := () {}
```

Invalid:
```dyn
module main
os := use "std/os"
os.println("hi")
```

## 1.3 Modules and visibility

Normative:
- declarations are private outside the module by default
- declarations are visible across all files in the same module
- `pub` marks a declaration public outside the module

Example:
```dyn
pub println := ...
```

Normative:
Binaries require a `main` binding.

Provisional:
Exact file-system-to-module mapping is implementation-defined in v0.1.

# 2. Lexical structure

## 2.1 Whitespace

Normative:
- spaces, tabs, and newlines may separate tokens
- whitespace is otherwise insignificant
- blank lines have no semantic effect

## 2.2 Statement termination

Normative:
Statements may be terminated by:
- newline
- semicolon
- block close `}`

Semicolons are optional.

Examples:
```dyn
x := 1
y := 2
```

```dyn
x := 1; y := 2
```

## 2.3 Comments

Normative:
- `//` begins a single-line comment
- `/* ... */` denotes a block comment
- `///` denotes a doc comment

Provisional:
Nested block comments are not specified in v0.1. A compiler may reject nested block comments.

## 2.4 Identifiers

Normative:
Identifier syntax:
- first character: ASCII letter or `_`
- subsequent characters: ASCII letter, digit, or `_`

Unicode identifiers are omitted in v0.1.

Examples:
- `x`
- `_temp`
- `Point2`

## 2.5 Keywords

Normative keyword set:
- `module`
- `packed`
- `type`
- `use`
- `pub`
- `mut`
- `struct`
- `enum`
- `if`
- `else`
- `match`
- `for`
- `return`
- `break`
- `continue`
- `defer`
- `comp`
- `inline`
- `or`
- `extern`

Keywords may not be used as identifiers.

## 2.6 Builtin identifiers

Normative:
Identifiers beginning with `$` are reserved builtins and may not be user-defined.

Examples:
- `$typeof`
- `$sizeof`
- `$compile_error`

## 2.7 Literal words

Normative:
The lexer recognizes these source words as literals, not identifiers:

- `true`
- `false`
- `null`

# 3. Namespaces, scope, and resolution

## 3.1 Unified lexical namespace

Normative:
Dyn uses a unified lexical namespace for:
- variables
- functions
- parameters
- imported module bindings
- type names
- type aliases
- comptime bindings

## 3.2 No shadowing

Normative:
A declaration is invalid if its identifier is already visible in the current lexical scope or any enclosing lexical scope.

Examples:
```dyn
x := 1

scope := () {
  // x := 2 // invalid
}
```

```dyn
Point := struct {}

f := (Point: i32) {} // invalid
```

## 3.3 No same-scope redeclaration

Normative:
Redeclaring a name in the same scope is invalid.

## 3.4 Member lookup is separate

Normative:
Member/field/associated lookup does not introduce lexical bindings and does not participate in lexical redeclaration rules.

Examples:
```dyn
os := use "std/os"
os.println("x")
```

```dyn
self.x
Point.origin
```

## 3.5 Labels

Normative:
Labels occupy a scoped control-flow namespace.
A label name may not conflict with another declaration while it is visible in the same scope.
The same spelling may be reused outside the labeled scope.

Example:
```dyn
scope := () {
  loop: for {
    break :loop
  }
}

loop := 1
```

## 3.6 Enum variant shorthand

Normative:
A shorthand enum variant like `.Red` is valid when the enum type can be inferred unambiguously from context.

# 4. Declarations and bindings

## 4.1 Binding declarations

Normative grammar:
```text
BindingDecl
  := Visibility? 'mut'? Identifier ':=' Expr
   | Visibility? 'mut'? Identifier ':' Type '=' Expr

ExternDecl
  := Visibility? Identifier ':=' 'extern' ExternSig

ExternSig
  := '(' FunctionTypeParamList? ')' Type? LinkNameOpt

LinkNameOpt
  := '=' StringLiteral
   | ε
```

Examples:
```dyn
x := 1
mut y := 2
z: i32 = 3
mut w: i32 = 4
```

## 4.2 Initialization requirement

Normative:
All bindings must be initialized at declaration.
Uninitialized declarations are invalid.

Invalid:
```dyn
x: i32
```

## 4.3 Mutability

Normative:
- bindings are immutable by default
- `mut` makes the binding mutable
- reassignment is only valid for mutable bindings

Examples:
```dyn
mut x := 1
x = 2
x += 1
```

Invalid:
```dyn
x := 1
x = 2
```

## 4.4 Associated declarations

Normative grammar:
```text
AssociatedDecl := Visibility? TypePath '.' Identifier ':=' Expr
```

Examples:
```dyn
Point.origin := Point{}
Point.new := (x: i32, y: i32) Point => .{ x, y }
```

Normative:
In v0.1, `TypePath` should be restricted to named type expressions for implementation simplicity.

## 4.5 Extern bindings

Normative:
Extern declarations are function-only and must use binding syntax.

Valid:
```dyn
write := extern (fd: i32, ptr: *u8, len: usize) i32 = "dynrt_fd_write"
```

Invalid:
```dyn
extern write: (fd: i32, ptr: *u8, len: usize) i32 = "dynrt_fd_write"
```

# 5. Types

## 5.1 Static typing

Normative:
Dyn is statically typed.
A binding’s type does not change.

## 5.2 Primitive and built-in type forms

Normative language-visible integer types:
- `i8 i16 i32 i64 i128`
- `u8 u16 u32 u64 u128`
- `isize usize`

Normative float types:
- `f32`
- `f64`

Other built-in type names:
- `bool`
- `type`
- `any`

Normative:
`void` is not written as a function return type in source syntax. Void-returning functions omit the return type.

## 5.3 Array, slice, pointer, optional, function, tuple, errorable types

Normative grammar:
```text
Type
  := NamedType
   | ArrayType
   | SliceType
   | PointerType
   | OptionalType
   | FunctionType
   | TupleType
   | ErrorableType
   | StructTypeExpr
   | EnumTypeExpr
```

```text
NamedType    := Identifier ('.' Identifier)*
ArrayType    := '[' Expr ']' Type
SliceType    := '[' ']' Type
PointerType  := '*' Type
OptionalType := '?' Type
FunctionType := '(' FunctionTypeParamList? ')' Type?
FunctionTypeParamList := FunctionTypeParam (',' FunctionTypeParam)* ','?
FunctionTypeParam := Identifier ':' ParamType
                   | ParamType
TupleType    := '{' TypeList? '}'
TypeList     := Type (',' Type)* ','?
ErrorableType := Type '!' ErrorTypeListOpt
ErrorTypeListOpt := ErrorTypeList | ε
ErrorTypeList := Type (',' Type)*
```

Examples:
```dyn
[5]i32
[]u8
*i32
?i32
(x: i32, y: i32) i32
()
{ i32, i32, i32 }
i32!
f32!MyErr
```

Normative:
`*mut T` and `[]mut T` are not ordinary type forms in v0.1. They are only valid in parameter/receiver type positions.

## 5.4 Struct types

Normative grammar:
```text
StructTypeExpr := 'struct' '{' StructFieldList? '}'
StructFieldList := StructField (',' StructField)* ','?
StructField := Identifier ':' Type DefaultFieldValue?
DefaultFieldValue := '=' Expr
```

Example:
```dyn
Point := struct {
  x: i32 = 0,
  y: i32 = 0,
}
```

## 5.5 Enum types

Normative grammar:
```text
EnumTypeExpr := 'enum' EnumReprOpt '{' EnumVariantList? '}'
EnumReprOpt := '(' EnumReprType ')' | ε
EnumReprType := 'u8' | 'u16' | 'u32' | 'u64' | 'usize'
EnumVariantList := EnumVariant (',' EnumVariant)* ','?
EnumVariant := Identifier PayloadType?
PayloadType := ':' Type
```

Examples:
```dyn
Color := enum {
  Red,
  Blue,
}

Token := enum {
  ident: []u8,
  number: i32,
  eof,
}
```

Normative:
Enums with payloads are tagged unions.

Normative:
Enum bodies contain variants only.
Associated values and functions use associated declarations outside the enum body:

```dyn
Token.invalid := 255
```

## 5.6 Type aliases

Normative:
Simple aliasing is allowed by ordinary binding syntax.

Example:
```dyn
MyInt := i32
```

Normative:
This is an alias, not a distinct nominal type.

## 5.7 Distinct/newtypes

Normative:
Distinct nominal newtypes are omitted in v0.1.

# 6. Literals

## 6.1 Integer literals

Normative supported forms:
- decimal: `123`
- hex: `0xff`
- binary: `0b1010`
- octal: `0o755`
- numeric separators: `1_000`

Normative:
The default type of an unsuffixed integer literal is `i32`.

Normative:
An integer literal may be contextually typed to another integer type if its value is representable in that type.

Examples:
```dyn
x := 1        // i32
y: i64 = 1    // valid
z: u8 = 255   // valid
```

Invalid:
```dyn
x: u8 = 256
```

## 6.2 Float literals

Normative forms include:
- `1.0`
- `0.5`
- `1e3`
- `1.5e-2`

Normative:
Default type is `f32`.

## 6.3 String literals

Normative:
String literals use double quotes.

Example:
```dyn
"hello"
```

Normative properties:
- behave as immutable static UTF-8 byte data
- surface type is `[]u8`
- no null terminator is implied
- indexing and slicing are byte-based

Normative:
A string literal is not directly mutable.

## 6.4 Char literals

Normative:
Char literals use single quotes.

Example:
```dyn
'a'
```

Normative properties:
- no dedicated `char` type exists in v0.1
- char literals are inferred unsigned code-unit integer literals
- ASCII/default char literals default to `u8`
- unicode escapes may widen as needed

## 6.5 Null literal

Normative:
`null` is the null value for optional types.

## 6.6 Array literals

Normative:
```text
ArrayLiteral := '[' ExprList? ','? ']'
ExprList := Expr (',' Expr)*
```

Examples:
```dyn
[1, 2, 3]
[]
```

Normative:
An array literal infers a fixed-size array type.

## 6.7 Tuple and anonymous struct literals

Normative tuple literal:
```dyn
.{ 1, 2, 3 }
```

Normative anonymous struct literal:
```dyn
.{ x: 1, y: 2 }
```

Normative:
The parser distinguishes tuple literal vs anonymous struct literal by presence of named fields.

## 6.8 Typed struct literals

Normative:
```text
TypedStructLiteral := Type '{' FieldInitList? ','? '}'
FieldInitList := FieldInit (',' FieldInit)*
FieldInit := Identifier ':' Expr | Identifier
```

Examples:
```dyn
Point{}
Point{ x: 1 }
Point{ x, y }
```

Normative:
Bare identifier field init is shorthand for `field: field`.

# 7. Expressions

## 7.1 Expression categories

Normative:
Expressions include:
- literals
- identifiers
- blocks
- function expressions
- calls
- member access
- indexing
- dereference
- unary/binary operator expressions
- if expressions
- match expressions
- composite literals
- `use` expressions
- type expressions

## 7.2 Primary expressions

Normative:
```text
PrimaryExpr
  := Identifier
   | Literal
   | '(' Expr ')'
   | BlockExpr
   | FunctionExpr
   | StructTypeExpr
   | EnumTypeExpr
   | ArrayLiteral
   | TupleLiteral
   | AnonStructLiteral
   | TypedStructLiteral
   | UseExpr
```

## 7.3 Postfix operations

Normative postfix operations:
- call: `f(...)`
- member access: `x.y`
- indexing: `x[y]`
- dereference: `x.*`
- optional unwrap: `x.?`
- error propagation/unwrap: `x.!`

These operations may chain.

Example:
```dyn
a.?.b[0].!
```

## 7.4 Prefix operations

Normative prefix operators:
- `!`
- unary `-`
- `~`
- `&`
- `&mut`
- `comp`

## 7.5 Binary operations

Normative binary operators:
Arithmetic:
- `+ - * / %`

Bitwise:
- `& | ^ << >>`

Comparison:
- `< <= > >= == !=`

Logical:
- `&& ||`

Range:
- `.. ..=`

Special:
- `or`

## 7.6 Precedence and associativity

Normative precedence from highest to lowest:

1. Postfix
- `()`
- `.`
- `[]`
- `.?`
- `.!`
- `.*`

2. Prefix
- `!`
- unary `-`
- `~`
- `&`
- `&mut`
- `comp`

3. Multiplicative
- `* / %`

4. Additive
- `+ -`

5. Shift
- `<< >>`

6. Bitwise and
- `&`

7. Bitwise xor
- `^`

8. Bitwise or
- `|`

9. Comparison
- `< <= > >=`

10. Equality
- `== !=`

11. Logical and
- `&&`

12. Logical or
- `||`

13. Range
- `.. ..=`

14. Optional/error defaulting
- `or`

Assignment is not an expression in v0.1.

Normative:
Binary operators are left-associative unless otherwise naturally constrained.
The compiler should reject ambiguous chained range forms unless intentionally implemented.

# 8. Statements and blocks

## 8.1 Blocks

Normative:
```text
Block := '{' Statement* '}'
```

A block introduces a new lexical scope.

## 8.2 Statements

Normative:
```text
Statement
  := BindingDecl
   | AssignmentStmt
   | ReturnStmt
   | BreakStmt
   | ContinueStmt
   | DeferStmt
   | IfStmt
   | ForStmt
   | MatchStmt
   | LabeledStmt
   | ExprStmt
   | DestructureDecl
   | DestructureAssign
```

## 8.3 Assignment statements

Normative:
Assignment is statement-only.

Grammar:
```text
AssignmentStmt := LValue AssignOp Expr
AssignOp := '=' | '+=' | '-=' | '*=' | '/=' | '%='
          | '&=' | '|=' | '^=' | '~=' | '<<=' | '>>='
```

LValue forms in v0.1:
- identifier
- member access
- index access
- dereference

## 8.4 Return

Normative:
```text
ReturnStmt := 'return' Expr?
```

Rules:
- `return` with no expression is valid only in a void-returning function
- a non-void function must return a value on all control-flow paths

## 8.5 Break and continue

Normative:
```text
BreakStmt := 'break' LabelRef? Expr?
ContinueStmt := 'continue' LabelRef?
LabelRef := ':' Identifier
```

Examples:
```dyn
break
break 5
break :loop
break :block 12
continue
continue :loop
```

## 8.6 Labels

Normative:
```text
LabeledStmt := Identifier ':' Statement
```

Labels may apply to loops and to statements whose enclosing expression/block may be broken from.

# 9. Functions

## 9.1 Function expressions

Normative grammar:
```text
FunctionExpr
  := ParamList FunctionReturnSpecOpt Block
   | ParamList FunctionReturnSpec '=>' Expr
   | 'inline' FunctionExpr

FunctionReturnSpecOpt
  := FunctionReturnSpec
   | ε

FunctionReturnSpec
  := ReturnType
   | ReturnType '!' ErrorTypeListOpt
   | '!' ErrorTypeListOpt
   | 'comp' Expr
   | 'comp' Expr '!' ErrorTypeListOpt
```

Examples:
```dyn
f := () {}
g := (x: i32) i32 { return x }
h := (x: i32) i32 => x * 2
```

Normative rules:
- params must always be typed
- return type is omitted for void
- `=>` form requires explicit return type
- block-bodied functions do not have implicit return
- functions are first-class values
- `() ! { ... }` is valid and denotes an errorable void-returning function
- `comp Expr` in return position denotes a compile-time-evaluated return type expression

## 9.2 Parameter list

Normative grammar:
```text
ParamList := '(' ParamListItems? ')'
ParamListItems := Param (',' Param)* ','?
Param := Identifier ':' ParamType DefaultArg?
DefaultArg := '=' Expr
```

## 9.3 Parameter types

Normative:
A parameter type may be:
- ordinary type
- mutating pointer parameter type
- mutating slice parameter type

Grammar:
```text
ParamType
  := Type
   | '*' 'mut' Type
   | '[' ']' 'mut' Type
```

Examples:
```dyn
x: i32
p: *i32
p: *mut i32
buf: []u8
buf: []mut u8
```

Normative:
`*mut T` and `[]mut T` are only valid in parameter/receiver positions in v0.1.

## 9.4 Function calls

Normative:
Call syntax uses:
```text
CallExpr := Expr '(' ArgList? ')'
ArgList := Arg (',' Arg)* ','?
Arg := Expr | Identifier ':' Expr
```

Calls support:
- positional args
- named args
- omitted trailing default args

Examples:
```dyn
add3(1, 2, 3)
add3(1)
add3(y: 3, z: 2)
add3(1, z: 4)
```

Normative:
A call with wrong arity or invalid named/default usage is a compile error.
After the first named argument, all following arguments must be named.

# 10. Control flow

## 10.1 If statements and expressions

Normative statement grammar:
```text
IfStmt := 'if' Condition StatementOrBlock ('else' (IfStmt | StatementOrBlock))?
```

Normative expression grammar:
```text
IfExpr := 'if' Condition ExprBranch 'else' ExprBranch
ExprBranch := Expr | Block
```

Examples:
```dyn
if x > 0 {
  return 1
} else {
  return 2
}
```

```dyn
y := if x > 0 1 else 0
```

Normative:
Conditions must be `bool`, except for optional-capture conditions.

## 10.2 Optional capture conditions

Normative grammar:
```text
OptionalCaptureCond := Expr ':' '|' Identifier? '|'
```

Example:
```dyn
if maybe: |v| {}
```

Normative:
This form is valid only when the condition expression has optional type `?T`.

Normative semantics:
- if the optional is non-null, the body executes
- the capture identifier, if present, is bound to the unwrapped value in the success branch
- if no identifier is present, the value is tested for non-nullness without introducing a binding

Provisional:
Multiple captures in a single condition are omitted from v0.1 unless already implemented.

## 10.3 Block values

Normative:
A block used in expression position must yield a value via `break`.

Examples:
```dyn
x := {
  break 1
}
```

```dyn
x := if cond {
  break 1
} else {
  break 0
}
```

Normative:
Function bodies are not block-value expressions and use `return`, not `break`.

## 10.4 For loops

Normative supported forms:
- range loop
- iterator loop
- conditional loop
- infinite loop

Examples:
```dyn
for 0..10: |i| {}
for arr: |item| {}
for x < 10 {}
for {}
```

Normative parsing strategy:
- `for { ... }` is infinite loop
- `for Expr ':' '|' ... '|'` is captured iterator/range loop
- `for Expr Block` is conditional loop

Normative:
`0..10` excludes `10`
`..=` is inclusive-range syntax

Provisional:
Reverse ranges are intended but exact lowering/semantics are implementation-defined in v0.1.

## 10.5 Match

Normative grammar:
```text
MatchExpr := 'match' Expr '{' MatchArmList '}'
MatchArmList := MatchArm (',' MatchArm)* ','?
MatchArm := Pattern MatchGuardOpt ':' MatchArmBody
MatchGuardOpt := 'if' Expr | ε
MatchArmBody := Expr | Block | CaptureBody
CaptureBody := '|' Identifier? '|' (Expr | Block)
```

Examples:
```dyn
match x {
  1: {},
  2..10: {},
  20, 21, 22: {},
  _: {},
}
```

```dyn
match partnered {
  .variant1: |i| {},
  .variant2: |v| {},
}
```

Normative patterns in v0.1:
- wildcard `_`
- literals
- literal ranges
- enum variant patterns
- comma-separated multi-patterns

Normative:
`match` may be used as expression or statement.
If used as expression, all arms must yield the same type.

Normative:
Exhaustiveness is checked.

Tuple/struct pattern matching is omitted in v0.1.

# 11. Errors and optionals

## 11.1 Optional types

Normative:
Optional type syntax is `?T`.

Examples:
```dyn
x: ?i32 = 1
y: ?i32 = null
```

## 11.2 Errorable types

Normative:
Errorable type syntax is:
```text
Type '!' ErrorTypeListOpt
ErrorTypeListOpt := ErrorTypeList | ε
```

Examples:
```dyn
i32!
f32!MyErr
```

Normative:
A bare trailing `!` indicates inferred error set/type.
A following type list constrains the error type.

## 11.3 Optional unwrap

Normative:
`x.?` unwraps an optional value.

Normative:
Unwrapping a definitely-null optional is a compile error if statically provable; otherwise runtime trap/error behavior is implementation-defined under safe-mode semantics.

## 11.4 Error propagation / unwrap

Normative:
`x.!` propagates or unwraps an errorable value.

Semantics:
- if `x` contains a value, evaluate to that value
- if `x` contains an error, return/propagate the error from the current function/scope context

Normative:
Using `.!` outside an error-compatible context is a compile error.

## 11.5 `or`

Normative:
`or` is valid only for:
- optional values
- errorable values

Examples:
```dyn
y := maybe() or 0
z := fallible() or return
a := fallible() or |e| {
  break 0
}
```

Normative semantics:
For optionals:
- if left side is non-null, yield unwrapped value
- otherwise evaluate right side

For errorables:
- if left side is value, yield value
- otherwise evaluate right side, optionally with captured error

Error capture form:
```text
Expr 'or' '|' Identifier? '|' ExprOrBlock
```

Normative:
If `or` appears in expression position and the left side’s success type is needed, the right side must:
- yield a value of the same type
- or exit control flow via `return` or `break`

## 11.6 Ignored errors

Normative:
Ignoring an errorable value without handling or propagation is a compile error.

# 12. Equality and comparison

## 12.1 Built-in equality

Normative:
`==` and `!=` are supported for:
- integers
- floats
- bool
- plain enums without payloads
- pointers
- char/code-unit integer values

Normative:
`==` and `!=` are not supported for:
- structs
- payload enums
- arrays
- slices
- string values as `[]u8`

Examples:
- `"a" == "a"` is invalid
- `'a' == 'a'` is valid

## 12.2 Ordering comparisons

Normative:
`< <= > >=` are supported only for numeric types in v0.1.

## 12.3 Composite equality

Normative:
Composite equality should be done via stdlib helpers.
No automatic structural comparison exists in v0.1.

# 13. Structs, tuples, enums

## 13.1 Struct literals

Normative:
Anonymous struct literals use:
```dyn
.{ x: 1, y: 2 }
```

Typed struct literals use:
```dyn
Point{ x: 1, y: 2 }
```

Normative:
`Point{ x, y }` is shorthand for `Point{ x: x, y: y }`.

## 13.2 Tuples

Normative:
Tuple literal syntax:
```dyn
.{ 1, 2, 3 }
```

Tuple type syntax:
```dyn
{ i32, i32, i32 }
```

Tuple destructuring:
```dyn
{ a, b, c } := tuple
```

Tuple indexed access:
```dyn
tuple[0]
```

Normative:
Tuple indices in `tuple[index]` must be compile-time constant integers when the base type is a tuple.

## 13.3 Destructuring

Normative grammar:
```text
DestructureDecl
  := '{' DestructureItems '}' ':=' Expr
   | '{' DestructureItems '}' ':' TupleType '=' Expr

DestructureAssign
  := '{' DestructureItems '}' '=' Expr

DestructureItems := DestructureItem (',' DestructureItem)* ','?
DestructureItem := Identifier | '_'
```

Examples:
```dyn
{ a, b, c } := tuple
{ x, y } = p
```

Normative:
`_` discards a value.

Provisional:
Exact struct destructuring assignment rules are partially provisional in v0.1 but should behave analogously to tuple destructuring by field name matching when implemented.

## 13.4 Enums

Normative:
Payloadless enums support equality.
Payload enums do not.

Examples:
```dyn
Color := enum { Red, Blue }
Token := enum { ident: []u8, eof }
```

# 14. Reference, pointer, and aliasing model

## 14.1 Ordinary reference-like types

Normative:
Ordinary pointer type is `*T`.
Ordinary slice type is `[]T`.

## 14.2 Mutable reference creation

Normative:
- `&x` creates immutable reference
- `&mut x` creates mutable reference
- `&mut x` requires mutable storage

## 14.3 Mutating parameter contracts

Normative:
Parameter forms `*mut T` and `[]mut T` indicate the function may mutate the referenced pointee/elements.

Examples:
```dyn
set := (out: *mut i32) {
  out.* = 5
}
```

```dyn
fill := (buf: []mut u8, value: u8) {
  // mutate buf elements
}
```

Normative:
Passing an argument to such a parameter requires mutable-reference semantics at the call boundary.

## 14.4 Methods

Normative:
Methods are associated functions attached with `Type.name := ...`.

Examples:
```dyn
Point.increment := (self: *mut Point) {
  self.x += 1
  self.y += 1
}
```

Method-call syntax:
```dyn
mut p := Point{ x: 0, y: 0 }
p.increment()
```

Normative:
A method call to receiver parameter `self: *mut T` lowers as if passing `&mut receiver`.
A method call to receiver parameter `self: *T` lowers as if passing `&receiver`.

## 14.5 Alias/liveness rules

Normative:
Dyn enforces lightweight last-use-based alias checking.

Rules:
1. Multiple immutable references to the same storage may coexist.
2. A mutable reference must be exclusive with respect to other live references to the same storage.
3. An immutable reference may not be used after an overlapping mutable reference is created.
4. A mutable reference may not be created while immutable references to the same storage remain live.
5. Liveness is determined by last use, not lexical declaration alone.
6. The compiler may be conservative if liveness is unclear.
7. Immutable references may be copied.
8. Mutable references may not be copied or aliased.
9. Borrowing is whole-value based in v0.1, not field-granular.

Valid:
```dyn
scope := () {
  mut r := 1
  p := &r
  mp := &mut r
  mp.* += 1
  os := use "std/os"
  os.println("ok")
}
```

Invalid:
```dyn
scope := () {
  mut r := 1
  p := &r
  mp := &mut r
  os := use "std/os"
  os.println(p.*)
}
```

## 14.6 Returning references to locals

Normative:
Returning references/pointers to local stack storage is a compile error.

## 14.7 Pointer arithmetic

Omitted:
Pointer arithmetic is not specified in v0.1.

# 15. Name resolution and typing rules

## 15.1 Resolution timing

Normative:
The compiler should:
1. parse the whole module/file set
2. collect declarations
3. resolve names in lexical scope order
4. type check expressions/statements

## 15.2 Function and type names

Normative:
Functions, types, aliases, imported modules, variables, and parameters all resolve within the same lexical namespace.

## 15.3 Closures

Normative:
Nested functions are allowed.
Closures capture outer bindings by reference.

Normative:
Captured mutability obeys ordinary alias/mutability rules.

## 15.4 Recursion and mutual recursion

Normative:
Recursion and mutual recursion are allowed.

Provisional implementation guidance:
A compiler may use multi-pass declaration collection to resolve mutually recursive declarations within a module.

# 16. Type checking

## 16.1 Declarations

Normative:
For `x := expr`, infer type of `expr` and bind `x` to that type.

For `x: T = expr`, type-check `expr` against `T`.

## 16.2 Assignments

Normative:
Assignment requires:
- left side is assignable
- left side binding/storage is mutable
- right side type is assignable/coercible to left side type

## 16.3 Integer conversions

Normative:
- integer literals may coerce to a target integer type if representable
- widening integer conversions from smaller to larger may be implicit
- narrowing conversions require explicit cast
- explicit cast syntax is `$as(T, value)`

## 16.4 Float/integer conversions

Normative:
Implicit conversion from integer literal to float target is allowed when context requires.
General numeric conversions outside literal-context require explicit cast unless otherwise specified.

## 16.5 Arrays and slices

Normative:
- an array literal infers fixed-size array type
- fixed-size arrays may coerce to slices
- mutable/immutable alias rules apply to references to arrays/slices, not by introducing separate ordinary slice types

## 16.6 String typing

Normative:
String literals type as `[]u8`.

## 16.7 Tuple typing

Normative:
Tuple literal `.{ e1, e2, ... }` has tuple type `{ T1, T2, ... }` where each `Ti` is the inferred type of `ei`.

## 16.8 Struct literal typing

Normative:
Anonymous struct literal `.{ field: expr, ... }` has anonymous struct type with those fields.
Typed struct literal `Point{ ... }` must match the declared fields of `Point`, using defaults for omitted fields when available.

## 16.9 Enum construction

Normative:
Payloadless variants are accessed as `Enum.Variant` or `.Variant` in inferable context.
Payload variants are constructed as calls:
```dyn
Enum.Variant(payload)
```

## 16.10 Equality typing

Normative:
The compiler must reject `==`/`!=` on unsupported composite types listed in section 12.

# 17. Comptime

## 17.1 Core rule

Normative:
`comp` marks expressions/values/parameters that must be compile-time known/evaluated.

Examples:
```dyn
List := (T: comp type) type => struct {
  items: []T,
}
```

## 17.2 Compile-time known values

Normative baseline:
Compile-time known values include:
- literals
- immutable bindings initialized from compile-time known expressions
- expressions composed entirely of compile-time known operands
- type values
- results of comptime-evaluable functions called with comptime-known arguments

Not compile-time known:
- mutable bindings
- runtime call results
- values depending on runtime state

## 17.3 Compile-time blocks

Normative:
`comp { ... }` evaluates its contents at compile time.

## 17.4 Inline

Normative:
`inline` may annotate functions and loops.
`inline for` indicates compile-time unrolling when the iteration space is compile-time known.

## 17.5 Type values

Normative:
`type` is a first-class compile-time value.
Functions may accept and return `type`.

## 17.6 Compile-time failures

Normative:
Passing a non-comptime-known value where `comp` is required is a compile error with source span.

# 18. Reflection and builtins

## 18.1 Reserved builtins

Normative builtin set in v0.1 includes:
- `$self`
- `$alignof`
- `$as`
- `$compile_error`
- `$fields`
- `$has_field`
- `$has_method`
- `$is_float`
- `$is_sint`
- `$is_uint`
- `$typeclass`
- `$memcpy`
- `$memset`
- `$offsetof`
- `$panic`
- `$sizeof`
- `$syscall`
- `$target`
- `$typename`
- `$typeof`

## 18.2 Builtin status

Normative:
- builtins are reserved
- user code may not define `$` names
- some builtins are compile-time only, some runtime, some mixed

## 18.3 Reflection philosophy

Normative:
Reflection should expose ordinary compile-time metadata values, not a separate macro language.

## 18.4 `$fields`

Normative:
`$fields(T)` or `$fields(v)` returns compile-time field metadata for struct/tuple-like forms.

Provisional:
Exact metadata record shape is implementation-defined in v0.1 but should be stable within a compiler implementation.

## 18.5 Type construction

Provisional:
Dyn intends a builtin such as `$type(...)` for compile-time type construction.
This is not fully specified in v0.1 and may be omitted until metadata shapes are fixed.

# 19. Imports and `use`

## 19.1 `use` as expression

Normative:
`use "path"` is an expression.

Example:
```dyn
os := use "std/os"
```

Normative:
`use` is valid in any scope.

## 19.2 Imported value

Normative:
`use "path"` yields a module namespace value/object whose public members are accessible by member access.

Example:
```dyn
os.println(...)
```

Normative:
Importing does not inject members directly into lexical scope unless explicitly rebound:

```dyn
println := (use "std/os").println
```

# 20. Allocators and memory management

## 20.1 General model

Normative:
Dyn uses explicit allocator-based memory management.
No garbage collection exists in v0.1.

## 20.2 Allocation error model

Normative:
Allocation failure is represented with errorable returns, not plain optionals.

## 20.3 Recommended typed allocator API

Normative library expectation for standard allocator surface:
```dyn
Allocator.create := (self: *mut Allocator, T: comp type) *T!AllocError
Allocator.destroy := (self: *mut Allocator, ptr: *T)

Allocator.alloc := (
  self: *mut Allocator,
  T: comp type,
  count: usize
) []T!AllocError

Allocator.free := (self: *mut Allocator, buf: []T)

Allocator.resize := (
  self: *mut Allocator,
  buf: []T,
  new_count: usize
) []T!AllocError

Allocator.dupe := (
  self: *mut Allocator,
  T: comp type,
  src: []T
) []T!AllocError
```

## 20.4 Ownership conventions

Normative convention:
- allocator-returned values are owned by caller unless documented otherwise
- slices are non-owning views unless returned from an owning allocation API
- APIs that create owned memory should take allocator explicitly

## 20.5 Arenas

Normative library expectation:
Arena allocators are a preferred ergonomic allocation style.

Provisional:
Exact arena API shape is library-defined, not core language syntax.

# 21. Diagnostics and safety modes

## 21.1 Required compile errors

Normative:
The compiler must reject at least:
- invalid redeclaration/shadowing
- wrong-arity calls
- type mismatches
- invalid assignment to immutable binding
- uninitialized declarations
- unsupported equality on composite types
- invalid use of `or`
- invalid use of `.!` outside compatible context
- invalid use of `.?`
- returning reference to local
- mutable-reference alias violations
- ignored errorable results
- using keyword as identifier

## 21.2 Warnings

Normative minimum recommended warnings:
- unused local binding
- unused parameter
- pointless always-null optional binding
- unreachable code

## 21.3 Safety modes

Normative baseline:
v0.1 defines safe mode as the semantic baseline.

Safe mode expectations:
- bounds checks enabled
- obvious runtime-failure conditions diagnosed when provable at compile time
- runtime traps/errors for invalid unchecked operations not rejected statically

Provisional:
Additional modes such as fast mode and optimization levels are allowed but not fully specified in v0.1.

# 22. Omitted or provisional areas

Omitted from v0.1:
- pointer arithmetic semantics
- distinct nominal newtypes
- full tuple/struct match destructuring
- full reflection metadata schema
- fully specified `$type(...)`
- unsafe blocks/syntax
- ABI/calling convention details
- C interop details
- async/threading
- field-level borrow disjointness
- user-defined operators
- operator overloading
- destructors/drop hooks

# 23. Minimal validity examples

## 23.1 Minimal program
```dyn
module main
main := () {}
```

## 23.2 Hello world
```dyn
module main
os := use "std/os"

main := () {
  os.println("Hello world")
}
```

## 23.3 Mutable reference mutation
```dyn
module main

add_into_num := (x: i32, y: i32, result: *mut i32) {
  result.* = x + y
}

main := () {
  mut res := 0
  add_into_num(1, 2, &mut res)
}
```

## 23.4 Error handling
```dyn
module main

BasicErr := enum { Ouch }

get_num := () i32!BasicErr {
  return .Ouch
}

main := () ! {
  x := get_num() or 0
}
```

## 23.5 Struct and method
```dyn
module main

Point := struct {
  x: i32 = 0,
  y: i32 = 0,
}

Point.increment := (self: *mut Point) {
  self.x += 1
  self.y += 1
}

main := () {
  mut p := Point{}
  p.increment()
}
```

# 24. Implementation guidance summary

A compiler implementing v0.1 should minimally contain:
1. lexer
2. parser
3. AST
4. multi-pass declaration collector
5. name resolver with no-shadowing enforcement
6. type checker
7. control-flow checker for returns/break values
8. optional/error analysis for `.?`, `.!`, `or`
9. alias/liveness checker for `&` / `&mut`
10. basic comptime evaluator for `comp` constructs and type-valued functions

That is now a real, compiler-oriented draft spec.

Important honesty note
An AI could use this to build a compiler frontend and a meaningful semantic analyzer, but there are still a few areas where implementation would need either:
- provisional choices
- or a follow-up spec appendix

If you want to make it even more “compiler-buildable,” the best next step is one of these:

1. AST and semantic rules appendix
Very implementation-focused.

2. formal grammar appendix
More parser-precise.

3. comptime and builtin semantics appendix
Needed for a more complete compiler.

4. alias checker algorithm appendix
Needed to implement your reference model cleanly.

My recommendation:
Next I should write:
- Appendix A: Formal grammar
- Appendix B: Semantic analysis rules
- Appendix C: Reference/alias checker algorithm

Those three would make this much more directly compilable by an AI or human.

If you want, I can start with Appendix A right now.
