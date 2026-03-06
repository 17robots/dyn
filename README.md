# The Dyn Language

## Rust compiler bootstrap

```
.
├── Cargo.toml
├── language_spec.md
└── src
├── compiler
│   ├── ast/
│   ├── diagnostics.rs
│   ├── lexer/
│   ├── mod.rs
│   ├── module_resolver.rs
│   ├── pipeline.rs
│   ├── parser/
│   └── sema/
    ├── lib.rs
    └── main.rs
```

Run the module resolver:

```bash
cargo run -- resolve <start_directory>
```

Run full module-resolve + lexer pass:

```bash
cargo run -- lex <start_directory>
```

Get lexer output as JSON:

```bash
cargo run -- lex <start_directory> --json
```

Run parser pass:

```bash
cargo run -- parse <start_directory>
```

Print parsed AST (debug view):

```bash
cargo run -- parse <start_directory> --ast
```

Run semantic declaration/import analysis:

```bash
cargo run -- analyze <start_directory>
```

Run AST->HIR lowering pipeline:

```bash
cargo run -- hir <start_directory>
```

Run HIR->MIR lowering pipeline:

```bash
cargo run -- mir <start_directory>
```

Build native executable (Go-style default output under `.dyn_build/`):

```bash
cargo run -- build <start_directory>
```

Build native executable with explicit output path:

```bash
cargo run -- build <start_directory> -o <output_path>
```

Build with optimization level selection:

```bash
cargo run -- build <start_directory> -O2
# or: cargo run -- build <start_directory> --opt-level 2
```

Resolver behavior right now:
- Recursively scans `.dyn` files
- Skips leading `//`, `///`, and `/* ... */` comments before module declaration checks
- Groups files by `(relative_directory + module_name)`
- Interns modules into stable `ModuleId`s based on sorted module keys
- Collects per-file diagnostics and reports all invalid files in one pass

Lexer contracts are defined in:
- Unified compiler diagnostics are shared in `src/compiler/diagnostics.rs`
- Token/keyword/operator contracts are defined in `src/compiler/lexer/token.rs`
- Numeric lexing rules are locked as constants, including `..` and `..=` precedence and `:`/`=` split behavior

Current lexer implementation status:
- Cursor utility is in `src/compiler/lexer/cursor.rs`
- Scanner pass in `src/compiler/lexer/scanner.rs` handles whitespace/comments/doc comments
- Scanner lexes identifiers, builtins, operators/delimiters, numeric literals, string literals, and char literals (with diagnostics + recovery)

Compiler pipeline status:
- `src/compiler/pipeline.rs` resolves modules, lexes all module files, and aggregates resolver + lexer diagnostics in one `LexSession`

AST planning status:
- Initial AST node families are scaffolded in `src/compiler/ast/` (items, expressions, patterns, types, operators, and node IDs)

Parser status:
- Recursive-descent parser scaffold is in `src/compiler/parser/mod.rs`
- Pipeline integration is available through `parse_project(...)` in `src/compiler/pipeline.rs`

Semantic-analysis prep status:
- Parser top-level segmentation has been tightened for example files (module declarations and top-level bindings are now split more reliably)
- Module-merged semantic input is scaffolded via `ModuleUnit` in `src/compiler/sema/module_unit.rs`
- Use `parse_project_with_module_units(...)` from `src/compiler/pipeline.rs` to get parsed files plus merged per-module declaration stubs
- First semantic passes are scaffolded in `src/compiler/sema/analyze.rs` (duplicate declaration checks and module import target resolution)
- Name/member resolution checks are now included for module-level expressions (`E4001` unresolved names, `E4004` private member access)
- Minimal type core + first type checks are in `src/compiler/sema/typeck.rs` (`E4005` mismatches, `E4006` mutability/null checks, basic numeric operator validation)
- Additional semantic passes now include call-arity/named-argument validation and control-flow legality checks (`E4007` break/continue context)
- Match exhaustiveness baseline check is included (`E4008` when no wildcard arm is present)
- Semantic name resolution now uses lexical scope traversal over AST expressions (including block scopes, for bindings, and match-pattern bindings)
- Type checking now includes function body return checking, scoped block bindings, and optional `or` fallback type compatibility
- Errorable flow typing is partially supported (`.!` force unwrap and `or` fallback on errorable values), and match exhaustiveness recognizes wildcard or full bool coverage
- Numeric type checking now models concrete integer/float widths internally (`Int { signed, bits }`, `Float { bits }`) with basic width/signed compatibility
- HIR scaffold is available in `src/compiler/hir/` and runnable with `cargo run -- hir <start_directory>`
- HIR lowering now includes semantic metadata (declaration `def_id` and inferred binding type strings where available)
- MIR scaffold is available in `src/compiler/mir/` with CFG blocks, terminators, and verification
- Native build scaffold is wired through Cranelift in `src/compiler/backend/cranelift.rs` via `cargo run -- build <start_directory>`
- Imported module member calls now lower to qualified function symbols, so calls like `io := use "my_io"; io.print(...)` execute reliably at runtime.
- Printing is std/module-owned (`io.print`/`io.println` style); there is no implicit global compiler `print`/`println`.

Backend planning notes are tracked in `BACKEND_PLAN.md`.

## Remaining milestones before backend/codegen

- Parser hardening
  - Increase nested function/block fidelity and gradually remove fallback-only recoveries.
  - Keep top-level segmentation stable while reducing tolerant parsing in hot paths.
- Semantic and type completeness
  - Expand compatibility and coercion rules for integer widths/signs and float widths.
  - Improve optional/errorable flow typing across more expression shapes.
  - Strengthen match exhaustiveness beyond wildcard/bool baseline (enum/range aware).
- Typed IR pipeline
  - HIR scaffold exists in `src/compiler/hir/`; continue enriching it with resolved symbols and explicit control-flow edges.
  - Add type attachments to lowered nodes to make backend lowering deterministic.
- Backend preparation
  - Finalize runtime/data-layout assumptions and calling convention strategy.
  - Decide LLVM IR vs bytecode VM first for codegen bring-up.
