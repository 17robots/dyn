# Dyn Language Specification v0.1 — Appendix A: Formal Grammar

Notes
- This is a parser-oriented grammar, not a fully LR-clean grammar.
- Expression parsing is precedence-based.
- Semantic restrictions are enforced after parsing.
- Some constructs are context-sensitive, especially typed struct literals and `*mut`/`[]mut` parameter types.

A1. Lexical tokens

Keywords:
```text
module use pub mut struct enum if else match for return break continue
defer comp inline or extern packed type
```

Literal words:
```text
true false null
```

Reserved builtin identifiers:
```text
$[A-Za-z_][A-Za-z0-9_]*
```

Identifiers:
```text
[A-Za-z_][A-Za-z0-9_]*
```

Integer literal families:
```text
decimal  := [0-9]([0-9_]*[0-9])?
hex      := 0[xX][0-9A-Fa-f]([0-9A-Fa-f_]*[0-9A-Fa-f])?
binary   := 0[bB][01]([01_]*[01])?
octal    := 0[oO][0-7]([0-7_]*[0-7])?
```

Float literal families:
```text
float :=
  ([0-9]([0-9_]*[0-9])?\.[0-9]([0-9_]*[0-9])?([eE][+-]?[0-9]+)?)
  | ([0-9]([0-9_]*[0-9])?[eE][+-]?[0-9]+)
```

String literal:
```text
" ... "
```

Char literal:
```text
' ... '
```

Operators and punctuation:
```text
:= : = => . , ; ? ! .? .! .* + - * / % < <= > >= == !=
&& || & | ^ ~ << >> += -= *= /= %= &= |= ^= ~= <<= >>=
( ) { } [ ] .. ..=
```

A2. Source file grammar

```text
SourceFile      := ModuleDecl TopLevelDecl*

ModuleDecl      := 'module' Identifier

TopLevelDecl    := Visibility? Decl
Visibility      := 'pub'

Decl            := BindingDecl
                 | ExternDecl
                 | AssociatedDecl
```

A3. Declarations

```text
BindingDecl     := MutOpt Identifier ':=' Expr
                 | MutOpt Identifier ':' Type '=' Expr

ExternDecl      := Identifier ':=' 'extern' ExternSig

ExternSig       := '(' FunctionTypeParamListOpt ')' ReturnTypeOpt LinkNameOpt
LinkNameOpt     := '=' StringLiteral | ε

MutOpt          := 'mut' | ε

AssociatedDecl  := TypePath '.' Identifier ':=' Expr

TypePath        := Identifier ('.' Identifier)*
```

A4. Statements and blocks

```text
Block           := '{' Statement* '}'

Statement       := BindingDecl
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

ExprStmt        := Expr

AssignmentStmt  := LValue AssignOp Expr

AssignOp        := '='
                 | '+=' | '-=' | '*=' | '/=' | '%='
                 | '&=' | '|=' | '^=' | '~=' | '<<=' | '>>='

ReturnStmt      := 'return' ExprOpt
ExprOpt         := Expr | ε

BreakStmt       := 'break' LabelRefOpt ExprOpt
ContinueStmt    := 'continue' LabelRefOpt

LabelRefOpt     := ':' Identifier | ε

LabeledStmt     := Identifier ':' Statement

DeferStmt       := 'defer' DeferBody
DeferBody       := Expr
                 | Block
                 | '|' IdentifierOpt '|' Block

IdentifierOpt   := Identifier | ε
```

A5. Functions

```text
FunctionExpr    := InlineOpt ParamList FunctionReturnSpecOpt Block
                 | InlineOpt ParamList FunctionReturnSpec '=>' Expr

InlineOpt       := 'inline' | ε

ParamList       := '(' ParamListItemsOpt ')'
ParamListItemsOpt := ParamListItems | ε
ParamListItems  := Param (',' Param)* CommaOpt
CommaOpt        := ',' | ε

Param           := Identifier ':' ParamType DefaultArgOpt
DefaultArgOpt   := '=' Expr | ε

ParamType       := Type
                 | '*' 'mut' Type
                 | '[' ']' 'mut' Type

FunctionReturnSpecOpt := FunctionReturnSpec | ε
FunctionReturnSpec := ReturnType
                    | ReturnType '!' ErrorTypeListOpt
                    | '!' ErrorTypeListOpt
                    | 'comp' Expr
                    | 'comp' Expr '!' ErrorTypeListOpt
ReturnType      := Type
ReturnTypeOpt   := ReturnType | ε
```

A6. Expressions

Expressions are parsed by precedence. For grammar reference:

```text
Expr            := IfExpr
                 | MatchExpr
                 | OrExpr
```

A7. `if`

```text
IfExpr          := 'if' Condition ExprBranch 'else' ExprBranch
IfStmt          := 'if' Condition StatementOrBlock ElseClauseOpt

ElseClauseOpt   := 'else' (IfStmt | StatementOrBlock) | ε

StatementOrBlock := Statement | Block
ExprBranch      := Expr | Block

Condition       := OptionalCaptureCond
                 | Expr

OptionalCaptureCond := Expr ':' '|' IdentifierOpt '|'
```

A8. `for`

```text
ForStmt         := 'for' ForHead StatementOrBlock

ForHead         := BlocklessInfinite
                 | IterHead
                 | CondHead

BlocklessInfinite := ε

IterHead        := Expr ':' Capture
CondHead        := Expr

Capture         := '|' IdentifierOpt '|'
```

Parsing note:
- `for { ... }` is infinite loop because `ForHead` is empty before a block.
- `for Expr : |x| ...` is iterator/range loop.
- `for Expr ...` without capture is conditional loop.

A9. `match`

```text
MatchExpr       := 'match' Expr '{' MatchArmListOpt '}'
MatchStmt       := MatchExpr

MatchArmListOpt := MatchArmList | ε
MatchArmList    := MatchArm (',' MatchArm)* CommaOpt

MatchArm        := Pattern MatchGuardOpt ':' MatchArmBody
MatchGuardOpt   := 'if' Expr | ε

MatchArmBody    := Expr
                 | Block
                 | '|' IdentifierOpt '|' Expr
                 | '|' IdentifierOpt '|' Block
```

A10. Patterns

```text
Pattern         := '_'
                 | Literal
                 | RangePattern
                 | EnumVariantPattern
                 | MultiPattern

RangePattern    := Literal '..' Literal
EnumVariantPattern := '.' Identifier
MultiPattern    := Pattern ',' Pattern (',' Pattern)*
```

A11. Type grammar

```text
Type            := ErrorableType

ErrorableType   := PrimaryType ErrorSuffixOpt
ErrorSuffixOpt  := '!' ErrorTypeListOpt | ε
ErrorTypeListOpt := ErrorTypeList | ε
ErrorTypeList   := Type (',' Type)*

PrimaryType     := NamedType
                 | ArrayType
                 | SliceType
                 | PointerType
                 | OptionalType
                 | FunctionType
                 | TupleType
                 | StructTypeExpr
                 | EnumTypeExpr

NamedType       := Identifier ('.' Identifier)*
ArrayType       := '[' Expr ']' Type
SliceType       := '[' ']' Type
PointerType     := '*' Type
OptionalType    := '?' Type
FunctionType    := '(' FunctionTypeParamListOpt ')' ReturnTypeOpt
FunctionTypeParamListOpt := FunctionTypeParamList | ε
FunctionTypeParamList := FunctionTypeParam (',' FunctionTypeParam)* CommaOpt
FunctionTypeParam := Identifier ':' ParamType
                   | ParamType
TupleType       := '{' TypeListOpt '}'
TypeListOpt     := TypeList | ε
TypeList        := Type (',' Type)* CommaOpt
```

A12. Struct/enum type expressions

```text
StructTypeExpr  := 'struct' '{' StructFieldListOpt '}'
StructFieldListOpt := StructFieldList | ε
StructFieldList := StructField (',' StructField)* CommaOpt
StructField     := Identifier ':' Type DefaultFieldValueOpt
DefaultFieldValueOpt := '=' Expr | ε

EnumTypeExpr    := 'enum' EnumReprOpt '{' EnumVariantListOpt '}'
EnumReprOpt     := '(' EnumReprType ')' | ε
EnumReprType    := 'u8' | 'u16' | 'u32' | 'u64' | 'usize'
EnumVariantListOpt := EnumVariantList | ε
EnumVariantList := EnumVariant (',' EnumVariant)* CommaOpt
EnumVariant     := Identifier PayloadTypeOpt
PayloadTypeOpt  := ':' Type | ε
```

Semantic note:
- enum bodies contain variants only; associated values and functions are declared separately with `TypePath '.' Identifier ':=' Expr`.

A13. Literals and literals-related expressions

```text
Literal         := IntegerLiteral
                 | FloatLiteral
                 | StringLiteral
                 | CharLiteral
                 | 'null'

ArrayLiteral    := '[' ExprListOpt ']'
ExprListOpt     := ExprList CommaOpt | ε
ExprList        := Expr (',' Expr)*

TupleLiteral    := '.' '{' ExprListOpt '}'
AnonStructLiteral := '.' '{' NamedFieldInitList CommaOpt '}'

NamedFieldInitList := NamedFieldInit (',' NamedFieldInit)*
NamedFieldInit  := Identifier ':' Expr

TypedStructLiteral := Type '{' FieldInitListOpt '}'
FieldInitListOpt := FieldInitList CommaOpt | ε
FieldInitList   := FieldInit (',' FieldInit)*
FieldInit       := Identifier ':' Expr
                 | Identifier
```

A14. Destructuring

```text
DestructureDecl := '{' DestructureItems '}' ':=' Expr
                 | '{' DestructureItems '}' ':' TupleType '=' Expr

DestructureAssign := '{' DestructureItems '}' '=' Expr

DestructureItems := DestructureItem (',' DestructureItem)* CommaOpt
DestructureItem  := Identifier | '_'
```

A15. Postfix chains

Postfix parsing applies to any primary/prefix expression:

```text
PostfixSuffix   := CallSuffix
                 | MemberSuffix
                 | IndexOrSliceSuffix
                 | OptionalUnwrapSuffix
                 | ErrorPropSuffix
                 | DerefSuffix

CallSuffix      := '(' ArgListOpt ')'
ArgListOpt      := ArgList CommaOpt | ε
ArgList         := Arg (',' Arg)*
Arg             := Expr
                 | Identifier ':' Expr

MemberSuffix    := '.' Identifier
IndexOrSliceSuffix := '[' SliceOrIndexBody ']'
SliceOrIndexBody := Expr
                 | ExprOpt RangeOp ExprOpt
ExprOpt         := Expr | ε
RangeOp         := '..' | '..='
OptionalUnwrapSuffix := '.' '?'
ErrorPropSuffix := '.' '!'
DerefSuffix     := '.' '*'
```

A16. `use`

```text
UseExpr         := 'use' StringLiteral
```

A17. Prefix operators

```text
PrefixExpr      := PrefixOp PrefixExpr
                 | PostfixExpr

PrefixOp        := '!'
                 | '-'
                 | '~'
                 | '&'
                 | '&mut'
                 | 'comp'
```

A18. Expression precedence table

Use Pratt/precedence parsing with:

```text
Postfix:        (), ., [], .?, .!, .*
Prefix:         ! - ~ & &mut comp
Mul:            * / %
Add:            + -
Shift:          << >>
BitAnd:         &
BitXor:         ^
BitOr:          |
Compare:        < <= > >=
Equality:       == !=
LogicalAnd:     &&
LogicalOr:      ||
Range:          .. ..=
OrDefault:      or
```

Assignment is statement-only.

# Dyn Language Specification v0.1 — Appendix B: Semantic Analysis Rules

B1. Compilation phases

Recommended frontend order:
1. lex
2. parse
3. collect module-level declarations
4. resolve names
5. infer/check types
6. validate control flow
7. validate optionals/errors
8. validate alias/reference rules
9. perform comptime evaluation where required
10. lower to later IR

B2. Declaration collection

Normative:
All top-level declarations in a module must be collected before resolving bodies to support:
- recursion
- mutual recursion
- type references across file order within a module

B3. Name resolution

B3.1 Lexical scope model

Normative:
Lexical scopes exist for:
- module body
- block
- function body
- nested block
- destructure bindings
- conditional capture bindings
- match capture bindings

B3.2 No shadowing enforcement

Normative:
When inserting a new binding into a scope, the compiler must reject it if the name already exists in:
- current scope
- any enclosing lexical scope

This applies to:
- variables
- functions
- params
- imports
- types
- aliases
- comptime bindings

B3.3 Associated items

Normative:
Associated items defined via `Type.name := value` do not create lexical `name` bindings. They are reachable only via:
- `Type.name`
- method-call lowering if eligible

B3.4 Labels

Normative:
Labels exist in a separate scoped control-flow namespace.
A label may not be duplicated while visible in the same nested labeled scope chain.

B3.5 Enum shorthand resolution

Normative:
`.Variant` resolves only if context determines a unique enum type compatible with that variant name.
Otherwise compilation fails.

B4. Type checking: declarations

B4.1 Inferred declarations

For:
```dyn
x := expr
```
Rules:
- infer type `T` of `expr`
- bind `x: T`

B4.2 Typed declarations

For:
```dyn
x: T = expr
```
Rules:
- resolve type `T`
- type-check `expr`
- require `expr` assignable to `T`

B4.3 Mutable declarations

`mut` affects assignment legality, not declared type identity.

B5. Assignability and coercions

B5.1 Exact assignment

Normative:
An expression is assignable to a target type if:
- types are identical
- or a permitted implicit coercion applies

B5.2 Permitted implicit coercions in v0.1

Normative:
1. integer literal to integer target, if representable
2. integer literal to float target
3. smaller integer to larger integer
4. array to slice
5. payloadless enum variant shorthand to known enum context
6. mutable binding reference to immutable parameter reference shape, where applicable via `&`

Not permitted:
- narrowing integer conversions
- general float/integer conversions
- composite structural conversions unless explicitly specified

B5.3 Explicit casts

Normative:
Explicit cast syntax:
```dyn
$as(T, value)
```

Compiler responsibilities:
- reject invalid casts
- allow standard numeric casts and other explicitly supported casts

Provisional:
Bitcast/reinterpret casts are omitted unless later specified.

B6. Integer rules

B6.1 Default integer literal type
- `i32`

B6.2 Default float literal type
- `f32`

B6.3 Mixed arithmetic

Normative:
- if one integer operand is smaller and the other larger, widening to the larger type is allowed
- narrowing result assignment requires explicit cast
- if no valid common type exists under these rules, reject

Examples:
```dyn
a: i16 = 1
b: i32 = 2
c := a + b // i32
```

B6.4 Overflow

Normative baseline:
- compile-time-provable overflow is compile error or compile-time diagnostic under safe mode
- runtime overflow follows safe-mode trap/check behavior

B6.5 Division/remainder

Normative:
- integer division truncates toward zero
- remainder sign follows dividend
- divide by zero is compile error if provable at compile time, otherwise runtime error/trap in safe mode

B7. Arrays, slices, strings, tuples

B7.1 Arrays
- `[e1, e2, ...]` => `[N]T`
- all elements must have compatible type

B7.2 Slices
- array may coerce to slice
- slice is non-owning view
- indexing/slicing are bounds-checked in safe mode

B7.3 Strings
- string literal type is `[]u8`
- indexing yields `u8`
- slicing yields `[]u8`

B7.4 Tuples
- `.{ e1, e2, ... }` => `{ T1, T2, ... }`
- tuple indexing requires compile-time constant integer index
- out-of-range tuple index is compile error

B8. Structs and enums

B8.1 Struct literals

Typed struct literal checking:
- target type must be struct
- each provided field must exist
- omitted fields must have defaults or be provided elsewhere if required
- no duplicate fields
- shorthand `x` means `x: x`

Anonymous struct literal:
- creates anonymous structural type with listed named fields

B8.2 Enum construction

Payloadless enum:
```dyn
Color.Red
.Red
```

Payload enum:
```dyn
Token.ident("abc")
```

Rules:
- variant must exist
- payload expression must match payload type

B8.3 Enum equality

Normative:
- payloadless enums support `==` and `!=`
- payload enums do not support built-in equality

B9. Function typing

B9.1 Function value typing

A function expression has:
- ordered parameter list
- return type (or void)
- default args metadata if present

B9.2 Void functions

Normative:
If return type is omitted, function is void-returning.

Rules:
- `return` with no value is permitted
- `return value` is invalid unless a return type is present

B9.3 Non-void functions

Normative:
All control-flow paths must produce a return value.

B9.4 `=>` functions

Normative:
`(params) T => expr`
is equivalent to a function returning `expr`.

No `=>` form exists without explicit non-void return type.

B10. Calls

B10.1 Arity and arguments

Normative:
A call is valid if:
- positional args satisfy required parameters in order
- named args target existing parameters
- no parameter is provided twice
- omitted parameters all have defaults
- no extra args remain

B10.2 Named arg ordering

Normative:
After the first named argument, all following arguments must be named.

B10.3 Method lowering

If expression:
```dyn
recv.method(a, b)
```
resolves to associated function:
```dyn
Type.method := (self: P, ...)
```
then lower to:
```dyn
Type.method(receiver_as_self, a, b)
```

Receiver lowering:
- if `self: *T`, use `&recv`
- if `self: *mut T`, use `&mut recv`
- otherwise use value form if later allowed

B11. `if`

B11.1 Conditions

Normative:
Condition must type-check as:
- `bool`
- or optional-capture form over `?T`

No general truthiness exists.

B11.2 Expression form

Normative:
If used as expression:
- both branches must yield values
- both branch result types must unify

If a branch is a block:
- that block must yield via `break`

B12. `match`

B12.1 Scrutinee typing
- type-check scrutinee
- each arm pattern must be valid against scrutinee type

B12.2 Arm result typing
If `match` is expression:
- all arm bodies must yield compatible type

B12.3 Exhaustiveness
Normative:
- payloadless enums must be exhaustive
- payload enums must be exhaustive by variant coverage
- integer/literal matches require `_` unless full coverage is provable
- wildcard `_` covers remaining cases

B12.4 Pattern typing
- literal patterns type-check against scrutinee
- range patterns require ordered comparable pattern type
- enum variant patterns require matching enum
- capture body `|x|` for payload enum arms binds payload value type

B13. Optionals

B13.1 Optional literal assignment

Examples:
```dyn
x: ?i32 = 1
y: ?i32 = null
```

B13.2 `.?`
Rules:
- operand must be `?T`
- result type is `T`
- provably-null unwrap is compile error
- non-provably-null unwrap compiles with safe-mode runtime failure semantics if null occurs

B13.3 `or` on optional

For:
```dyn
lhs or rhs
```
where `lhs: ?T`:
- success type is `T`
- if non-null, expression yields unwrapped `T`
- if null, evaluate `rhs`

`rhs` must:
- yield `T`
- or exit via `return`/`break`

B13.4 Optional-capture `if`

For:
```dyn
if opt: |v| body
```
Rules:
- `opt` must be `?T`
- `v`, if present, is bound as `T` in the success branch scope only

B14. Errorables

B14.1 Errorable type form
- `T!`
- `T!E1,E2,...`

B14.2 `.!`
Operand must be errorable.
If success:
- yield inner value
If error:
- propagate error out of current compatible context

B14.3 `or` on errorables

For `lhs: T!E...`:
- if success, yield `T`
- if error, evaluate right branch
- capture form binds error value

Examples:
```dyn
x := fallible() or 0
fallible() or return
y := fallible() or |e| {
  break 0
}
```

B14.4 Error compatibility

Normative:
Using `.!` or returning an error from an inner call requires current function/block/error context to support compatible error propagation.

B14.5 Ignored errorables

Normative:
An errorable expression used as statement must still be handled; bare ignored result is compile error.

B15. Equality and operators

B15.1 `==` / `!=`
Allowed on:
- ints
- floats
- bool
- pointers
- payloadless enums

Rejected on:
- structs
- slices
- arrays
- payload enums

B15.2 Ordering operators
Allowed on numeric types only.

B16. Comptime typing

B16.1 `comp` params

For:
```dyn
f := (T: comp type) ...
```
rules:
- argument must be compile-time known
- type-check at call site before normal instantiation/evaluation

B16.2 Type-valued functions

If a function returns `type`, it must be evaluated at compile time.

B16.3 Compile-time known set

A value is compile-time known if:
- literal
- immutable binding initialized from compile-time known expression
- pure expression over compile-time known operands
- type value
- result of comptime-evaluable call with comptime-known args

Mutable bindings are never comptime-known.

B16.4 Compile-time failure
If non-comptime-known value is supplied where `comp` required:
- emit compile error with source span

B17. Diagnostics expectations

At minimum, compiler should produce errors for:
- redeclaration/shadowing
- unresolved names
- invalid type use
- invalid assignment
- wrong arity
- invalid `or`/`.?`/`.!`
- missing return
- bad borrow/alias use
- unsupported equality
- duplicate field in struct literal
- invalid enum variant
- invalid capture usage

Warnings recommended:
- unused variable
- unused parameter
- always-null optional binding
- unreachable code

# Dyn Language Specification v0.1 — Appendix C: Reference and Aliasing Checker Algorithm

This appendix gives an implementable baseline algorithm for Dyn’s lightweight last-use-based alias checking.

C1. Goal

Enforce:
- immutable references may coexist
- mutable references are exclusive
- exclusivity is based on live use, not lexical declaration alone
- mutable references cannot be copied
- analysis is whole-value based, not field-granular

C2. Tracked entities

For each borrowable storage place, track a borrow key.

Borrow keys in v0.1 are whole-value identities such as:
- local variable binding
- parameter binding
- dereferenced pointer target if statically known borrow origin
- array/struct binding as one unit

Field-level splitting is not performed in v0.1.

C3. Reference kinds

```text
BorrowKind = Shared | Mutable
```

Shared:
- created by `&x`

Mutable:
- created by `&mut x`

C4. Borrow records

For each created borrow/reference value, track:
- origin borrow key
- borrow kind
- creation point
- last-use point
- whether movable/copyable
- current owner temp/local if stored

Shared refs are copyable.
Mutable refs are not copyable.

C5. Prepass: last-use analysis

Before alias validation, perform a backward or SSA-like pass per function to determine last use of:
- local bindings
- reference values
- parameter references
- temporaries where practical

Minimum acceptable implementation:
- statement-index based last-use approximation
- conservatively extend last use to end of containing block if uncertain

C6. Core rules

Rule 1: Shared borrow creation
Creating `&x` is valid if there is no currently-live mutable borrow of origin `x`.

Rule 2: Mutable borrow creation
Creating `&mut x` is valid if:
- `x` is mutable storage
- there is no currently-live shared borrow of `x`
- there is no currently-live mutable borrow of `x`

Rule 3: Shared borrow use
Using a shared borrow is invalid if a mutable borrow of the same origin became live before that use and overlaps.

Rule 4: Mutable borrow use
Using a mutable borrow is invalid if any competing borrow of same origin overlaps.

Rule 5: Mutable borrow copy
Assigning/copying a mutable borrow to another binding is invalid.

Example invalid:
```dyn
mut x := 1
p := &mut x
q := p
```

Rule 6: Shared borrow copy
Shared borrow copy is valid.

Rule 7: Calls
Passing a borrow to a function counts as a use at the call site.
If the callee parameter is `*mut T` / `[]mut T`, treat the call argument as requiring a mutable borrow at that point.

Rule 8: Method lowering
Lower methods before alias validation or model method calls as equivalent borrow-requiring calls.

C7. Simple implementation strategy

Per function body:
1. Build CFG or statement order graph.
2. Compute conservative last-use indices for local values and borrow values.
3. Walk statements in order maintaining active borrows per origin.
4. At creation of `&x`:
   - expire borrows whose last-use < current index
   - reject if active mutable exists for origin
   - register shared borrow
5. At creation of `&mut x`:
   - expire borrows whose last-use < current index
   - reject if any active borrow exists for origin
   - register mutable borrow
6. At any use of reference value:
   - ensure it has not been invalidated by overlap rules
7. At assignment/copy:
   - if RHS is mutable borrow, reject
8. At block joins/branches:
   - merge active borrow sets conservatively
   - if uncertain, keep borrow active longer

C8. Example accepted

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

Reason:
- `p` has no uses after creation of `mp`
- its live range ends before `mp` starts

C9. Example rejected

```dyn
scope := () {
  mut r := 1
  p := &r
  mp := &mut r
  os := use "std/os"
  os.println(p.*)
}
```

Reason:
- `p` remains live after `mp` creation
- shared and mutable borrows overlap

C10. Whole-value borrowing

Because borrowing is not field-granular in v0.1, reject:
```dyn
mut p := Point{ x: 1, y: 2 }
px := &mut p.x
py := &p.y
```

if modeled via direct field-origin borrow sharing with `p` as one unit.

Simplest implementation:
- any borrow of a field maps to the enclosing root local binding’s borrow key

C11. Borrows through references

Provisional simplification for v0.1:
- if borrow origin through pointer dereference cannot be statically tied to a unique local/parameter root, alias checker may conservatively reject or skip advanced validation
- minimum guaranteed borrow checking applies to direct locals/params and method receiver lowering

C12. Lifetime ending

Borrow lifetime ends at last use, not declaration scope end.

If precise last use cannot be computed:
- conservatively end at block end

C13. Return restrictions

Reject:
- returning `&local`
- returning borrow/reference rooted in local stack storage

Accept:
- returning references rooted in parameters or longer-lived storage if otherwise type-correct and alias-valid

C14. Interaction with slices

Treat mutable slice borrow creation analogously to mutable pointer borrow creation:
- `[]mut T` parameter call requires mutable borrow of underlying slice origin
- shared slice usage overlaps like shared pointer borrow
- copying mutable slice borrow values is invalid if represented as mutable borrow entities

C15. Minimal implementation target

A v0.1-compliant compiler may initially restrict full alias checking to:
- locals
- parameters
- method receivers
- direct `&` / `&mut` expressions
- direct borrow passing to calls

and conservatively reject more complex alias cases.

# Dyn Language Specification v0.1 — Appendix D: Builtins and Comptime Semantics

This appendix defines:
- builtin function semantics
- compile-time evaluation rules
- reflection behavior baseline
- type-construction status
- constraints for compiler implementation

D1. Overview

Normative:
Dyn uses ordinary language execution for compile-time computation.
There is no separate macro language in v0.1.

Compile-time behavior is driven by:
- `comp`
- `inline`
- `type` values
- builtins beginning with `$`

D2. Compile-time evaluation contexts

D2.1 Contexts requiring compile-time evaluation

Normative:
An expression must be evaluated at compile time if it appears in a context requiring a compile-time-known value, including:
1. arguments to `comp` parameters
2. expressions under explicit `comp`
3. type-level expressions that must resolve to a concrete type
4. array lengths
5. tuple indices
6. other language constructs explicitly requiring compile-time constants

Examples:
```dyn
Vec := (T: comp type, N: comp usize) type => struct {
  data: [N]T,
}
```

```dyn
x := comp if use_f64 f64 else f32
```

D2.2 Compile-time known values

Normative:
A value is compile-time known if it is:
- a literal
- an immutable binding initialized from compile-time known expressions
- a pure expression over compile-time known operands
- a type value
- the result of a compile-time-evaluable function called with compile-time known args
- metadata produced by reflection builtins

Normative:
A mutable binding is never compile-time known.

Examples:
```dyn
a := 3          // comptime-known
b: i32 = 3      // comptime-known
mut c := 3      // not comptime-known
d := a + 1      // comptime-known
```

D2.3 Compile-time execution failure

Normative:
If an expression required to be compile-time known is not compile-time known, compilation fails with an error.

D3. `comp`

D3.1 Prefix `comp`

Normative:
`comp expr` forces compile-time evaluation of `expr`.

Examples:
```dyn
x := comp (1 + 2)
```

```dyn
selected := comp if flag T1 else T2
```

Normative:
If `expr` cannot be evaluated at compile time, compilation fails.

D3.2 `comp` blocks

Normative:
`comp { ... }` evaluates the block at compile time.

Inside a `comp` block, the compiler may:
- create local bindings
- evaluate conditionals and loops
- call comptime-evaluable functions
- inspect types/metadata
- emit compile errors via `$compile_error`

Provisional:
Direct declaration emission from inside `comp` blocks is implementation-dependent unless lowered through ordinary returned/generated values and attached declarations.

D3.3 `comp` parameters

Normative:
A parameter declared with `comp`:
```dyn
f := (T: comp type) ...
```
requires that argument to be compile-time known.

This applies to:
- types
- integers
- enums
- other compile-time value categories

Examples:
```dyn
Vec := (T: comp type, N: comp usize) type => struct {
  data: [N]T
}
```

D4. `inline`

D4.1 Inline functions

Normative:
`inline` on a function requests/means semantic inlining.
A compliant compiler should inline such functions or treat them as compile-time-expandable where required by semantics.

Example:
```dyn
id := inline (x: i32) i32 => x
```

D4.2 Inline loops

Normative:
`inline for` requires the loop to be unrolled when iteration space is compile-time known.

Example:
```dyn
inline for 0..4: |i| {
  do_thing(i)
}
```

If iteration space is not compile-time known, compilation fails.

D5. Type values

D5.1 `type`

Normative:
`type` is a first-class compile-time value category.
A value of type `type` denotes a Dyn type.

Examples:
```dyn
List := (T: comp type) type => struct {
  items: []T
}
```

D5.2 Type equality

Normative baseline:
Two named references to the same resolved type are equal as type values.

Provisional:
Generated/constructed type identity beyond straightforward structural equivalence is implementation-defined in v0.1 unless names/instances are interned consistently.

Compiler guidance:
- canonicalize generated type values where possible
- treat identical structural type expressions generated through the same construction path as equal when practical

D6. Builtins overview

D6.1 Builtin namespace

Normative:
Builtins are reserved identifiers beginning with `$`.

D6.2 Builtin categories

Normative builtins in v0.1 are divided into:
1. type/value inquiry
2. classification
3. reflection
4. diagnostics
5. low-level memory/system
6. conversions

Builtin list:
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

D7. Builtin semantics

D7.1 `$typeof`

Normative:
```text
$typeof(expr) -> type
```

Returns the compile-time type value of `expr`.

Example:
```dyn
T := $typeof(1) // i32
```

D7.2 `$typename`

Normative:
```text
$typename(T) -> []u8
```

Returns the compiler’s canonical name string for type `T`.

Provisional:
Exact formatting of complex/generated type names is implementation-defined in v0.1.

D7.3 `$sizeof`

Normative:
```text
$sizeof(T) -> usize
```

Returns size in bytes of `T`.

Requires:
- `T` must be a complete concrete type

D7.4 `$alignof`

Normative:
```text
$alignof(T) -> usize
```

Returns alignment in bytes of `T`.

Requires:
- `T` must be a concrete type with defined layout/alignment

D7.5 `$as`

Normative:
```text
$as(T, expr) -> T
```

Performs explicit conversion/cast to type `T`.

Compiler responsibilities:
- reject invalid conversions
- allow supported numeric casts
- allow identity casts
- other cast classes are provisional unless separately specified

D7.6 `$compile_error`

Normative:
```text
$compile_error(msg)
```

Compile-time-only builtin.
Emits a compile error with message `msg` and aborts compilation at that point.

`msg` must be compile-time known and string-compatible.

D7.7 `$fields`

Normative:
```text
$fields(T) -> FieldMetaSequence
$fields(v) -> FieldMetaSequence
```

If given a value, equivalent to `$fields($typeof(v))`.

Supported targets in v0.1:
- structs
- tuple types
- anonymous structs
- possibly payload structures embedded in enums where implemented

Returns compile-time metadata describing fields.

Provisional:
Exact metadata shape is implementation-defined in v0.1, but must be iterable at compile time and expose at least:
- field name
- field type
- field position/order

Compiler guidance:
Represent as compile-time array of metadata structs.

D7.8 `$has_field`

Normative:
```text
$has_field(T, name) -> bool
```

Returns whether type `T` has a field named `name`.

`name` must be compile-time known string-compatible data.

D7.9 `$has_method`

Normative:
```text
$has_method(T, name) -> bool
```

Returns whether type `T` has an attached associated function/method with that name.

Normative:
This refers only to attached associated items, not hypothetical UFCS free functions.

D7.10 `$is_float`, `$is_sint`, `$is_uint`

Normative:
```text
$is_float(T) -> bool
$is_sint(T)  -> bool
$is_uint(T)  -> bool
```

Type classifiers for compile-time branching.

D7.11 `$offsetof`

Normative:
```text
$offsetof(T, field_name) -> usize
```

Returns byte offset of named field in struct type `T`.

Requires:
- `T` must be a concrete struct type with defined layout
- `field_name` must identify an existing field

Provisional:
Field-name argument representation is implementation-defined but must be compile-time known.

D7.12 `$self`

Provisional:
`$self` is reserved for method/associated-context introspection.
Its exact behavior is not fully specified in v0.1.
A compiler may reserve the identifier without implementing semantics until needed.

D7.13 `$typeclass`

Provisional:
Reserved for future typeclass-like or trait-like mechanisms.
Not semantically required in v0.1.

D7.14 `$memcpy`

Normative:
```text
$memcpy(dst, src, count)
```

Low-level memory copy builtin.

Baseline constraints:
- compile/type-check pointer/byte-address compatibility
- intended for low-level/runtime use
- overlapping copy behavior is implementation-defined unless specified later

Compiler guidance:
Treat as intrinsic call with low-level semantics.

D7.15 `$memset`

Normative:
```text
$memset(dst, byte_value, count)
```

Low-level memory set builtin.

Compiler guidance:
Treat as intrinsic.

D7.16 `$panic`

Normative:
```text
$panic(msg?)
```

Aborts execution with runtime panic/trap.

May be used in runtime code.
If called in comptime evaluation, causes compile-time failure.

D7.17 `$syscall`

Provisional:
Low-level system-call intrinsic.
Exact ABI/argument/return semantics are platform-dependent and not fully specified in v0.1.

A compiler may expose it as intrinsic placeholder without stable cross-platform guarantees.

D7.18 `$target`

Provisional:
Returns compile-time target information.
Exact metadata shape is implementation-defined in v0.1.

D8. Reflection metadata requirements

D8.1 Minimum field metadata

Normative minimum:
`$fields(...)` metadata items must expose enough information for compile-time code to determine:
- field name
- field type
- field position

Compiler may expose additional properties:
- alignment
- offset
- default presence

D8.2 Enum reflection

Normative intent:
Enum variant reflection must exist in Dyn’s reflection model.

Provisional:
No exact builtin name/metadata schema is fixed in v0.1.
A compiler may postpone full enum reflection if not required by the implemented standard library subset.

D9. Comptime function evaluation

D9.1 Eligible functions

Normative:
A function call may be evaluated at compile time when:
- all required inputs are compile-time known
- its body uses only operations valid in comptime
- any transitive calls are comptime-valid

D9.2 Forbidden runtime-only operations during comptime

Normative baseline:
The compiler must reject comptime evaluation of operations that fundamentally require runtime state, unless the builtin explicitly supports comptime semantics.

Examples:
- runtime I/O
- target-dependent system calls
- runtime-only memory behavior not modeled at compile time

D9.3 Side effects in comptime

Normative baseline:
Compile-time side effects are limited to:
- producing compile-time values
- emitting diagnostics
- constructing types/metadata
- declaration-like effects supported by the compiler’s comptime model

Runtime side effects from comptime execution are invalid.

D10. Type construction

D10.1 Status

Provisional:
Dyn intends to support direct compile-time type construction via a builtin such as:
```text
$type(...)
```

D10.2 v0.1 implementation guidance

A compiler implementing v0.1 may:
- reserve `$type`
- omit it initially
- or implement a limited internal form sufficient for stdlib experimentation

If implemented, it should support constructing at least:
- struct types
- enum types
- tuple types

D11. Standard library mapping philosophy

Normative intent:
Builtin reflection concepts should correspond to stdlib-level metadata types where possible, such as:
- `builtin.Field`
- `builtin.EnumField`
- target metadata records

This mapping is conceptual in v0.1 and does not require exact stdlib names yet.

# Dyn Language Specification v0.1 — Appendix E: AST Schema and Lowering Rules

This appendix defines:
- recommended AST schema
- semantic AST distinctions
- lowering rules for method calls, block values, `or`, `.!`, etc.
- a good implementation shape for an AI compiler builder

E1. AST overview

Recommended compiler pipeline:
1. Parse into CST or direct AST
2. Normalize to semantic AST
3. Resolve names/types
4. Lower sugar constructs
5. Emit typed IR

The AST should preserve source spans on all nodes.

E2. Source file AST

```text
SourceFile {
  module_name: Ident
  decls: Vec<TopLevelDecl>
  span: Span
}
```

```text
TopLevelDecl =
  | BindingDecl
  | AssociatedDecl
```

E3. Declaration AST

```text
BindingDecl {
  visibility: Visibility
  mutable: bool
  name: Ident
  explicit_type: Option<TypeNode>
  value: Expr
  span: Span
}
```

```text
AssociatedDecl {
  visibility: Visibility
  owner: TypePath
  name: Ident
  value: Expr
  span: Span
}
```

```text
Visibility = Private | Public
```

E4. Statement AST

```text
Stmt =
  | BindingStmt(BindingDecl)
  | Assign {
      target: LValue,
      op: AssignOp,
      value: Expr,
      span: Span,
    }
  | Return {
      value: Option<Expr>,
      span: Span,
    }
  | Break {
      label: Option<Ident>,
      value: Option<Expr>,
      span: Span,
    }
  | Continue {
      label: Option<Ident>,
      span: Span,
    }
  | Defer {
      mode: DeferMode,
      body: DeferBody,
      span: Span,
    }
  | IfStmt {
      cond: CondExpr,
      then_branch: Box<StmtOrBlock>,
      else_branch: Option<Box<StmtOrBlock>>,
      span: Span,
    }
  | ForStmt {
      label: Option<Ident>,
      kind: ForKind,
      body: Box<StmtOrBlock>,
      inline: bool,
      span: Span,
    }
  | MatchStmt {
      value: Expr,
      arms: Vec<MatchArm>,
      span: Span,
    }
  | LabelStmt {
      label: Ident,
      stmt: Box<Stmt>,
      span: Span,
    }
  | ExprStmt {
      expr: Expr,
      span: Span,
    }
  | DestructureDecl {
      items: Vec<DestructureItem>,
      explicit_type: Option<TypeNode>,
      value: Expr,
      span: Span,
    }
  | DestructureAssign {
      items: Vec<DestructureItem>,
      value: Expr,
      span: Span,
    }
```

Supporting nodes:
```text
StmtOrBlock = Stmt | Block
```

```text
Block {
  stmts: Vec<Stmt>
  span: Span
}
```

```text
DeferMode = Normal | ErrorOnly(Option<Ident>)
```

```text
DeferBody = ExprBody(Expr) | BlockBody(Block)
```

E5. Expression AST

```text
Expr =
  | IdentExpr {
      name: Ident,
      span: Span,
    }
  | LiteralExpr {
      lit: Literal,
      span: Span,
    }
  | BlockExpr {
      block: Block,
      span: Span,
    }
  | FunctionExpr(FunctionNode)
  | CallExpr {
      callee: Box<Expr>,
      args: Vec<Arg>,
      span: Span,
    }
  | MemberExpr {
      object: Box<Expr>,
      member: Ident,
      span: Span,
    }
  | IndexExpr {
      object: Box<Expr>,
      index: Box<Expr>,
      span: Span,
    }
  | DerefExpr {
      object: Box<Expr>,
      span: Span,
    }
  | OptionalUnwrapExpr {
      object: Box<Expr>,
      span: Span,
    }
  | ErrorPropExpr {
      object: Box<Expr>,
      span: Span,
    }
  | PrefixExpr {
      op: PrefixOp,
      rhs: Box<Expr>,
      span: Span,
    }
  | BinaryExpr {
      lhs: Box<Expr>,
      op: BinaryOp,
      rhs: Box<Expr>,
      span: Span,
    }
  | IfExpr {
      cond: CondExpr,
      then_branch: Box<ExprBranch>,
      else_branch: Box<ExprBranch>,
      span: Span,
    }
  | MatchExpr {
      value: Box<Expr>,
      arms: Vec<MatchArm>,
      span: Span,
    }
  | UseExpr {
      path: StringLiteral,
      span: Span,
    }
  | StructTypeExpr(StructTypeNode)
  | EnumTypeExpr(EnumTypeNode)
  | ArrayLiteral {
      elems: Vec<Expr>,
      span: Span,
    }
  | TupleLiteral {
      elems: Vec<Expr>,
      span: Span,
    }
  | AnonStructLiteral {
      fields: Vec<FieldInitNamed>,
      span: Span,
    }
  | TypedStructLiteral {
      ty: TypeNode,
      fields: Vec<FieldInit>,
      span: Span,
    }
```

E6. Condition AST

Separate condition representation is useful:

```text
CondExpr =
  | Normal(Expr)
  | OptionalCapture {
      expr: Expr,
      binding: Option<Ident>,
      span: Span,
    }
```

Provisional:
If multi-capture conditions are later added, extend `CondExpr`.

E7. Function AST

```text
FunctionNode {
  inline: bool,
  params: Vec<ParamNode>,
  return_type: Option<TypeNode>,
  body: FunctionBody,
  span: Span,
}
```

```text
FunctionBody =
  | BlockBody(Block)
  | ExprBody(Expr)
```

```text
ParamNode {
  name: Ident,
  ty: ParamTypeNode,
  default_value: Option<Expr>,
  span: Span,
}
```

```text
ParamTypeNode =
  | Normal(TypeNode)
  | MutPtr(TypeNode)
  | MutSlice(TypeNode)
```

E8. Type AST

```text
TypeNode =
  | NamedType {
      path: Vec<Ident>,
      span: Span,
    }
  | ArrayType {
      len: Expr,
      elem: Box<TypeNode>,
      span: Span,
    }
  | SliceType {
      elem: Box<TypeNode>,
      span: Span,
    }
  | PointerType {
      elem: Box<TypeNode>,
      span: Span,
    }
  | OptionalType {
      inner: Box<TypeNode>,
      span: Span,
    }
  | TupleType {
      elems: Vec<TypeNode>,
      span: Span,
    }
  | ErrorableType {
      ok: Box<TypeNode>,
      errs: Vec<TypeNode>, // empty vec means inferred error set
      span: Span,
    }
  | StructType(StructTypeNode)
  | EnumType(EnumTypeNode)
```

```text
StructTypeNode {
  fields: Vec<StructFieldNode>,
  span: Span,
}
```

```text
StructFieldNode {
  name: Ident,
  ty: TypeNode,
  default_value: Option<Expr>,
  span: Span,
}
```

```text
EnumTypeNode {
  variants: Vec<EnumVariantNode>,
  span: Span,
}
```

```text
EnumVariantNode {
  name: Ident,
  payload: Option<TypeNode>,
  span: Span,
}
```

E9. Match AST

```text
MatchArm {
  pattern: PatternNode,
  capture: Option<Ident>,
  body: MatchBody,
  span: Span,
}
```

```text
MatchBody =
  | ExprBody(Expr)
  | BlockBody(Block)
```

```text
PatternNode =
  | Wildcard {
      span: Span,
    }
  | LiteralPattern {
      lit: Literal,
      span: Span,
    }
  | RangePattern {
      start: Literal,
      end: Literal,
      span: Span,
    }
  | EnumVariantPattern {
      name: Ident, // shorthand .Variant
      span: Span,
    }
  | MultiPattern {
      items: Vec<PatternNode>,
      span: Span,
    }
```

E10. Destructuring AST

```text
DestructureItem =
  | Bind(Ident)
  | Discard
```

For v0.1, tuple destructure and struct destructure can share syntax nodes and be distinguished during type checking.

E11. Literal AST

```text
Literal =
  | IntLit {
      repr: String,
      value: BigInt,
      base: IntBase,
    }
  | FloatLit {
      repr: String,
      value: RationalOrString,
    }
  | StringLit {
      value: Vec<u8>,
    }
  | CharLit {
      value: u32,
    }
  | NullLit
```

Compiler guidance:
- preserve original token text where useful for diagnostics
- store parsed numeric value for semantic checks

E12. Lowering overview

A good compiler should lower parse AST to semantic AST with the following transformations:
1. method call lowering
2. `=>` function body normalization
3. `or` normalization
4. block-expression validation
5. receiver borrow lowering
6. enum shorthand resolution after typing context known

E13. Lowering: `=>` bodies

Lower:
```dyn
f := (x: i32) i32 => x + 1
```

to semantic equivalent:
```text
FunctionBody::ExprBody(BinaryExpr(...))
```

or normalize to block:
```text
{
  return x + 1
}
```

Recommendation:
Keep original distinction until type-checking, then lower to canonical function IR.

E14. Lowering: method calls

Given:
```dyn
recv.method(a, b)
```

Resolve `method`:
1. determine type of `recv`
2. look up attached associated function on that type
3. if found, lower to ordinary call

Examples:

Case 1:
```dyn
Point.sum := (self: *Point) i32 => self.x + self.y
p.sum()
```

Lower to:
```dyn
Point.sum(&p)
```

Case 2:
```dyn
Point.inc := (self: *mut Point) { self.x += 1 }
p.inc()
```

Lower to:
```dyn
Point.inc(&mut p)
```

Failure cases:
- if receiver is immutable and method needs `*mut`, emit compile error
- if no attached method exists, method call resolution fails

E15. Lowering: `or`

Surface forms:
```dyn
lhs or rhs
lhs or return
lhs or |e| rhs
lhs or |e| { ... }
```

Recommended semantic lowering:

For optional:
```text
match lhs {
  Some(v) => v,
  None => rhs
}
```

For errorable:
```text
match lhs {
  Ok(v) => v,
  Err(e) => rhs_with_optional_capture
}
```

Since Dyn does not expose `Some/None` or `Ok/Err` syntax necessarily, this is internal lowering only.

Compiler should keep source-level distinction for diagnostics.

E16. Lowering: `.!`

Surface:
```dyn
fallible().!
```

Lower internally to propagation logic:
```text
temp := fallible()
if temp is error:
  return error
else:
  extract value
```

Must preserve current function error context.

E17. Lowering: `.?`

Surface:
```dyn
opt.?
```

Lower internally to:
```text
temp := opt
if temp is null:
  runtime fail / compile fail if provable
else:
  extract value
```

E18. Lowering: block-valued expressions

For expression-position blocks:
```dyn
x := {
  break 1
}
```

Represent block as expression node and later lower to IR block with value slots.

Validation rule:
- every reachable path in expression block must terminate with `break value`
- otherwise compile error

Function bodies are excluded from this rule and use `return`.

E19. Lowering: `if` expression

Example:
```dyn
x := if cond 1 else 0
```

Lower to IR-level branch expression with merged result slot.
If branches are block-valued, first lower branch blocks to block-value form.

E20. Lowering: `match` expression

Lower to:
- decision tree over patterns
- each arm writes to result slot or branches to exit block

Exhaustiveness should be checked before lowering or during decision-tree construction.

E21. Lowering: tuple indexing

Surface:
```dyn
t[0]
```

If `t` has tuple type:
- require index expr compile-time constant integer
- lower to tuple element projection by ordinal

If `t` has array/slice type:
- lower to normal index op

E22. Lowering: destructuring

Tuple destructuring:
```dyn
{ a, b, c } := t
```

Lower to:
```text
tmp = t
a = tmp[0]
b = tmp[1]
c = tmp[2]
```

Struct destructuring:
```dyn
{ x, y } = p
```

Lower to:
```text
x = p.x
y = p.y
```

Discard `_` emits no binding.

E23. Lowering: `use`

Surface:
```dyn
os := use "std/os"
```

Lower to a special module-handle constant/object for resolver/import system.
This is not a normal runtime string-based module load.

E24. Semantic symbol tables

Recommended symbol categories:
```text
SymbolKind =
  | Value
  | Function
  | Type
  | Module
  | Param
  | Local
  | ComptimeValue
  | Label
  | AssociatedItem
```

Even though many share one unified lexical namespace, tracking categories helps diagnostics.

E25. Type checker output / typed AST

After type checking, annotate expressions with:
- resolved type
- value category (rvalue/lvalue/place/ref)
- comptime-known flag if applicable
- borrow origin if applicable for alias checker

Recommended typed expression wrapper:
```text
TypedExpr {
  expr: Expr
  ty: TypeId
  value_kind: ValueKind
  comptime_known: bool
  borrow_origin: Option<BorrowKey>
  span: Span
}
```

E26. LValue classification

For assignment and mutability checks, classify these as assignable places:
- mutable local binding
- dereferenced mutable-reference-compatible target
- struct field of mutable place
- indexed element of mutable place

Tuple indexing is not assignable in v0.1 unless tuple place mutability semantics are intentionally implemented.

E27. IR-facing lowering recommendations

A backend-facing IR should have explicit nodes/instructions for:
- local binding
- branch / conditional branch
- loop entry/exit
- block value result
- call
- method-lowered call
- load/store
- aggregate literal construction
- enum tag/payload construction
- optional/error tag tests
- compile-time constant/type nodes

E28. Minimal compiler compliance target

A compiler is v0.1-minimally compliant if it can:
1. parse the grammar in Appendix A
2. build AST roughly equivalent to Appendix E
3. perform semantic checks from Appendix B
4. support compile-time evaluation and builtins from Appendix D to the extent required by implemented language/library features
5. reject unsupported provisional/omitted features cleanly
