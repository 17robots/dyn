# Dyn Language Specification v1 (Baseline)

Status: locked baseline for current implementation.

This document is the authoritative v1 baseline. If other docs conflict, this file wins.

## Compatibility and Versioning

- Language version: `v1` baseline.
- Patch-level compiler changes may improve diagnostics and implementation details without intentionally changing source semantics.
- Any semantic change that would alter accepted/rejected programs must be called out as a spec update.

## 1. Source Files and Modules

- A module is defined by all `.dyn` files in one directory that share the same `module <name>` declaration.
- `use "path/to/mod"` resolves as:
  - directory: `path/to`
  - module name: `mod`
- Import fails if no file in target directory declares that module.
- Multiple module declarations in one file are invalid; conflicting names are diagnosed.

## 2. Program Entry

- CLI entry defaults:
  - `main.dyn` if present
  - otherwise exactly one `.dyn` file in cwd
  - otherwise error (`EntryNotFound` or `AmbiguousEntry`)
- Executable entry function is `main`.

## 3. Declarations

- Supports declarations with optional `pub` visibility.
- Grouped declaration forms are supported.
- Functions can be declared and referenced out-of-order at module scope.
- Shadowing outer names inside nested scope is diagnosed.
- Assignment to immutable bindings is diagnosed.

## 4. Expressions and Statements

Implemented baseline includes:
- literals (including strings)
- arithmetic and comparisons
- unary operators and logical operators with short-circuit behavior
- calls and member access
- assignment
- blocks
- `if` expressions
- `match` expressions
- `for`, `break`, `continue`
- labeled blocks
- `defer` (parsing/lowering path supported)

Type/flow constraints currently enforced:
- `if` and `for` conditions must be `bool` (when known)
- calling non-function values is invalid
- `break`/`continue` outside loops is invalid
- statements after `break`/`continue` in the same block are diagnosed as unreachable
- postfix operators:
  - `expr.*` pointer dereference form
  - `expr.?` optional unwrap form
  - `expr.!` error unwrap form
- assignment targets are restricted to identifiers and dereference forms (`expr.*`)

## 5. Visibility and Resolution

- Module member access via import alias must reference exported (`pub`) members.
- Accessing non-public or missing members is an error with diagnostics.

## 6. Semantic Checks (Current Baseline)

- unknown identifier errors
- basic type compatibility checks (see type compatibility matrix)
- function call arity/type checks (current function-literal model)
- mutability and shadowing checks
- loop legality checks
- aggregate duplicate member checks
- typed function return-path checks: function body must produce a value on all paths

### Type Compatibility Matrix (Current)

Types in current checker: `unknown`, `void`, `bool`, `int`, `float`, `string`, `char`, function/module/aggregate placeholders.

Pointer/unwrap baseline:
- pointer type annotation syntax: `*T` and `*mut T`
- address-of syntax: `&expr`
- `expr.*` expects pointer value
- assignment through `expr.*` requires mutable pointer (`*mut T`), otherwise error `cannot assign through immutable pointer`
- `expr.?` requires optional-typed value (`'.?' expects optional value`)
- `expr.!` requires error-typed value (`'.!' expects error value`)

Compatibility rules:
- exact type equality is compatible
- `unknown` is compatibility-permissive (to avoid cascading failures)
- `int` and `float` are mutually compatible for numeric operations/assignments
- `bool`, `string`, `char` are not compatible with numeric types

Inference/coercion boundaries:
- no implicit string/char/bool coercion to numeric
- numeric merge selects `float` if either side is float, else `int`
- function call argument checks use declared parameter annotations where present

## 7. IR and Backend Baseline

- Lowering target is stack instruction IR.
- Cross-module calls lower to external symbols with module-prefixed naming.
- Internal ABI contract (current):
  - calling convention: `stack_i64`
  - scalar parameter model: homogeneous `param_type` with `param_count`
  - scalar return type tracked as `ret_type`
  - ABI validator rejects missing symbols, arg-count mismatch, call-conv mismatch, and param-type mismatch
- Direct x86_64 asm path supports:
  - control flow
  - function calls
  - multi-object linking
  - rodata strings with RIP-relative addressing

## 8. CLI Baseline

- `dyn check [entry.dyn] [--json]`
- `dyn build [entry.dyn] [-o out] [--emit-obj|--emit-asm] [--work-dir dir] [--json]`
- `dyn run [entry.dyn] [--work-dir dir] [-- arg ...]`
- `dyn clean [--work-dir dir] [--json]`

Exit behavior:
- success: `0`
- expected CLI/build/check errors: nonzero (`1` currently)
- `run`: when program exits normally, dyn exits with same program exit code

## 9. Platform Baseline

- Supported target in current baseline: Linux x86_64.
- Unsupported artifact/target configurations are rejected by backend codegen.

## 10. Out of Scope for v1 Baseline

These are not fully locked yet:
- richer coercion system beyond current numeric rules
- full control-flow proof for every return-path shape
- multi-target backend support beyond Linux x86_64
- full JSON diagnostics schema parity across all commands
- lowering/codegen execution semantics for pointer/optional/error operators (currently diagnosed at frontend and not lowered)

## 11. Conformance

Compiler behavior is considered conformant to this baseline when:
- relevant parser/semantic/backend tests pass
- CLI behavior matches section 8
- module resolution follows section 1
