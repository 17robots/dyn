# Self-Hosting Status

Checked on 2026-04-11.

## Current Baseline

The project currently has three different realities:

1. The Rust compiler in `src/compiler/` is the only working bootstrap implementation.
2. The bundled `std/` is intended to support a Dyn-written compiler, but many APIs are still placeholders.
3. There are two Dyn compiler trees:
   - `compiler-dyn/` is a newer rewrite, but it is still skeletal.
   - `compiler-dyn/old/` is much more complete, but it targets older language surface and older std assumptions.

`cargo test -q` passes for the Rust compiler baseline.

## What Blocks Self-Hosting Today

### 1. `compiler-dyn/` is not yet a usable compiler

Examples:

- `compiler-dyn/main.dyn` is effectively empty.
- `compiler-dyn/parser.dyn` stops near the start of file parsing.
- several files still contain internal inconsistencies that would need a bring-up pass before they can even serve as the new canonical compiler source.

Conclusion:
This tree is not the fastest route to a first self-hosted bootstrap.

### 2. `compiler-dyn/old/` is closer, but not source-compatible with the current language

Running the Rust bootstrap compiler against `compiler-dyn/old/` shows a large mismatch set, including:

- older expression and operator surface such as word-form `and`
- enum-body members that the current parser rejects
- places that rely on older control-flow and return-style assumptions
- std APIs such as `Vec`, allocator helpers, file I/O, argument handling, and formatted output that are not implemented yet

Conclusion:
`compiler-dyn/old/` is the better source of logic, but it needs a compatibility port rather than a direct handoff.

### 3. `std` still has important gaps

The Dyn compiler code currently expects these aggregate imports:

- `use "std/mem"`
- `use "std/os"`
- `use "std/str"`
- `use "std/collections"`

High-value missing or partial areas are:

- `std/mem`: typed allocation helpers and a real allocator backend
- `std/collections`: `Vec` API and storage management
- `std/os`: file reading, process args, environment, stdout/stderr helpers
- `std/io`: buffered/complete read-write helpers and non-placeholder printing

## Recommended Bring-Up Order

### Stage 1: Keep Rust as the bootstrap compiler

Do not treat self-hosting as “switch compilers now.”
The Rust compiler should remain the authoritative implementation while the Dyn compiler is brought up incrementally.

### Stage 2: Finish the minimum compiler-facing stdlib

Priority order:

1. `std/mem`
2. `std/collections/vec`
3. `std/os/file`
4. `std/os/process`
5. `std/os/fs`
6. `std/str`

The practical target is not a broad general-purpose stdlib.
The target is “enough stdlib for compiler code to allocate, grow vectors, read files, parse strings, print diagnostics, and inspect args/env.”

### Stage 3: Choose one Dyn compiler line and commit to it

Recommended:

- use `compiler-dyn/old/` as the logic donor
- port it toward the current language/spec/std surface
- only keep pieces of `compiler-dyn/` that are materially better than the old implementation

Reason:
The old tree has substantially more compiler substance today, even though it is out of date.

### Stage 4: Define bootstrap milestones

A realistic bootstrap ladder is:

1. Rust compiler analyzes Dyn compiler sources cleanly.
2. Dyn compiler lexes one file.
3. Dyn compiler parses one file.
4. Dyn compiler runs semantic checks on one file.
5. Dyn compiler can process its own source subset.
6. Dyn compiler can compile a helper binary.
7. Dyn compiler compiles a newer version of itself.

That is the first credible self-hosting path.

## Immediate Next Work

The best next steps are:

1. finish the compiler-facing stdlib surface, starting with memory + vector + OS basics
2. add compatibility work or source ports so `compiler-dyn/old/` analyzes with the current bootstrap compiler
3. only then resume work on the newer `compiler-dyn/` rewrite, if it still offers a clear structural advantage

## Practical Read

Self-hosting is achievable here, but not as a near-term flip.
The shortest path is:

- Rust compiler stays in charge
- stdlib becomes real enough for compiler code
- `compiler-dyn/old/` gets ported into the current language
- the Dyn compiler earns each phase of the pipeline one step at a time
