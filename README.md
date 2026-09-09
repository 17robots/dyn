# Dyn bootstrap compiler

Build from repository root:

```sh
make
./build/dyn check tests/empty
./build/dyn build tests/empty
./empty
make test
```

Current compiler lowers `fn main()`, void `return`, typed and inferred primitive locals,
primitive expressions, assignments, and checked arithmetic. Bare expressions are not valid statements.
Scoped `if`/`else`, condition and infinite `for` loops, `break`, `continue`, and branch-local
`return` lower to LLVM control-flow blocks. `for item in collection` traverses arrays and slices;
`continue` advances before retesting.
Nominal structs lower to LLVM named structs; packed declarations lower to packed LLVM bodies.
Construction starts from zero, applies declaration-order defaults, then explicit literal fields.
Function signatures are collected before body checking, enabling forward calls and recursion.
LLVM emission declares every function before generating bodies and preserves typed parameters,
results, and aggregate value semantics.

`ir.h` exposes typed IR through two operations: `dyn_ir_lower` and `dyn_ir_free`. Lowering
removes source spans/names except emitted symbols, normalizes compound assignments, and validates
all value, statement, local, function, aggregate, and child-list references. LLVM lowering never
reads semantic AST data.

Pointer types are interned as `(pointee, const)` pairs and copied into typed IR. LLVM uses opaque
thin pointers. Every generated dereference and pointer-based field access checks nil and target
alignment in debug and release; failure enters `dyn_panic` and exits 101.
Fixed array types and slice descriptors are interned beside pointers and preserved in typed IR.
LLVM uses native arrays and `{ptr, i64}` slice values. Array literals zero-fill omitted elements;
index and range guards remain enabled in release builds. Arrays copy by value and slices copy their
descriptor. Pointer-binding `for *item` / `for *const item` remains deferred.
Enums use calculated tag/payload layouts and LLVM tagged aggregates. `case` normalizes integer
ranges, rejects overlap, proves integer/enum exhaustiveness, and copies payload bindings.
Later constructs receive explicit not-implemented diagnostics. Output is static Linux x86-64
ELF from LLVM object generation and `ld.lld` (or development fallback `ld`).

See `docs/compiler.md`, `docs/debugging.md`, `docs/language.md`, `docs/decisions.md`, and
`docs/todo.md`.
