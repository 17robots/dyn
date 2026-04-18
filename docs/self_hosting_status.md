# Self-Hosting Status

Checked on 2026-04-14.

## Current Baseline

The project currently has two meaningful realities:

1. The Rust compiler in `src/compiler/` is the only working bootstrap implementation.
2. `compiler-dyn/` now lexes, parses, and runs a semantic pass for a single file under the Rust bootstrap compiler, but it is still only a frontend bring-up tree.
3. The bundled `std/` is much closer to compiler-facing viability, but runtime behavior is still incomplete in some important paths.

`cargo test -q` passes for the Rust compiler baseline.

## What Blocks Self-Hosting Today

### 1. `compiler-dyn/` is still not a full compiler driver

Current state:

- `compiler-dyn/parser.dyn` is no longer skeletal; it parses a substantial current-language surface.
- `compiler-dyn/sema.dyn` performs a real declaration/scope/name-analysis pass.
- `compiler-dyn/main.dyn` now has a minimal single-file `lex|parse|analyze` CLI path.

Still missing:

- project/module graph loading
- multi-file import resolution
- real lowering/type checking parity with Rust compiler
- backend handoff or code generation

Conclusion:
This tree is now valid as the active frontend bring-up path, but it is still not a self-hosted bootstrap compiler.

### 2. `std` still has important gaps

The Dyn compiler code currently expects these aggregate imports:

- `use "std/mem"`
- `use "std/os"`
- `use "std/str"`
- `use "std/collections"`

High-value missing or partial areas are:

- `std/io`: generic printing still placeholder for `any`
- `std/os`: enough for single-file bring-up, not yet full project-driver ergonomics
- allocator-backed returned values in self-host paths need continued ownership discipline
- runtime coverage is still thin compared to compile-only coverage

## Recommended Bring-Up Order

### Stage 1: Keep Rust as the bootstrap compiler

Do not treat self-hosting as “switch compilers now.”
The Rust compiler should remain the authoritative implementation while the Dyn compiler is brought up incrementally.

### Stage 2: Finish the minimum compiler-facing stdlib behavior

Priority order:

1. `std/io`
2. `std/os/file`
3. `std/os/process`
4. `std/collections/vec`
5. `std/str`

The practical target is not a broad general-purpose stdlib.
The target is “enough stdlib for compiler code to allocate, grow vectors, read files, parse strings, print diagnostics, and inspect args/env.”

### Stage 3: Keep `compiler-dyn/` as the active self-host path

Recommended:

- continue the current `compiler-dyn/` tree
- port logic from older sources only selectively
- avoid splitting effort across parallel compiler implementations

### Stage 4: Define bootstrap milestones

A realistic bootstrap ladder is:

1. Rust compiler analyzes Dyn compiler sources cleanly.
2. Dyn compiler lexes one file.
3. Dyn compiler parses one file.
4. Dyn compiler runs semantic checks on one file.
5. Dyn compiler resolves/imports a multi-file project.
6. Dyn compiler lowers a compatible frontend output for Rust backend consumption.
7. Dyn compiler processes its own source subset.
8. Dyn compiler compiles a newer version of itself.

That is the first credible self-hosting path.

## Immediate Next Work

The best next steps are:

1. finish compiler-facing std runtime behavior, especially IO and diagnostic formatting
2. add self-host project loading/import resolution
3. push `compiler-dyn` semantic coverage toward Rust frontend parity

## Practical Read

Self-hosting is achievable here, but not as a near-term flip.
The shortest path is:

- Rust compiler stays in charge
- stdlib becomes real enough for compiler code
- `compiler-dyn/` stays active
- stdlib becomes trustworthy enough for compiler workloads
- the Dyn compiler earns each phase of the pipeline one step at a time
