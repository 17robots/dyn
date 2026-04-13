# Dyn Self-Hosting Plan

## Goal

Move `compiler-dyn/` from prototype frontend pieces to a bootstrap-capable Dyn compiler frontend, then use that frontend to replace Rust compiler stages incrementally instead of attempting a one-shot rewrite.

## Current state

- `compiler-dyn/` analyzes cleanly under the Rust compiler.
- Present modules:
  - `ast.dyn`
  - `diagnostics.dyn`
  - `lexer.dyn`
  - `parser.dyn`
  - `main.dyn`
- `lexer.dyn` is the most complete self-host slice.
- `parser.dyn` is still mostly stubbed.
- diagnostics helpers are not feature-complete yet.
- std/platform selection now flows through `--target`, so frontend code can depend on platform imports instead of hardcoded host assumptions.

## Hard blockers

1. Real parser
The self-host compiler cannot advance until `parser.dyn` can build an AST for at least:
- module declarations
- top-level bindings
- `use` expressions
- function literals
- block expressions
- literals, names, calls, field access
- struct and enum type expressions

2. Stable diagnostic utilities
Need working implementations for:
- path normalization
- sorting
- dedupe
- deterministic formatting helpers

3. Frontend driver
Need one Dyn entry path that does:
- load source files
- lex
- parse
- collect diagnostics
- exit nonzero on error

4. AST alignment
Keep `compiler-dyn` AST surface aligned with current language decisions:
- no `bool` type spelling
- `u1` for truth-typed values
- current operator and declaration surface only

## Recommended bootstrap order

### Phase 1: frontend can parse itself enough to inspect source

1. Finish parser skeleton:
- token cursor helpers
- module decl
- doc comments
- identifiers
- minimal primary expressions
- minimal top-level binding parsing

2. Add parser smoke coverage:
- parse `module main`
- parse `x := 1`
- parse `os := use "std/os"`
- parse `main := () i32 => 0`

3. Add deterministic diagnostics helpers.

### Phase 2: declaration collector in Dyn

1. Build a Dyn declaration collector for:
- modules
- imports
- bindings
- type bindings
- externs

2. Emit a simple symbol table dump or intermediate summary.

3. Compare collector output against Rust compiler behavior on fixture programs.

### Phase 3: type and semantic bootstrap

1. Port type expression lowering.
2. Port name resolution.
3. Port type inference/checking.
4. Port diagnostic emission parity tests.

### Phase 4: backend boundary

1. Keep Cranelift backend in Rust initially.
2. Feed Rust MIR/backend from Dyn frontend output, or a compatible serialized IR.
3. Only then decide whether MIR lowering or backend pieces move into Dyn.

## Good next tasks

- implement `compiler-dyn/parser.dyn` token cursor and module parsing
- add a Rust integration test that `analyze_project(\"compiler-dyn\")` stays green
- add a parser smoke function in `compiler-dyn/main.dyn`
- fill diagnostics helper stubs in `compiler-dyn/diagnostics.dyn`

## Things to avoid

- do not try to port backend first
- do not require full language support before first useful bootstrap milestone
- do not let `compiler-dyn` drift from live std or target model
