# SDK/compiler hardening followup

Scope: reject generic struct literals everywhere; grammar/compiler support alignment,
bounded TAR metadata, incremental LSP stress, compiler phase/memory measurements,
and storage/failure contracts. Native platform testing excluded by request.

## Changes

- Generic struct literal syntax was already absent from both checked-in grammars.
  Removed obsolete AST lowering code describing it as merely unimplemented.
  Sixteen global/local/nested/return and qualified/type-argument examples must fail
  Tree-sitter parsing, compiler check/build, and LSP diagnostics. Local aliases remain
  explicitly unsupported, with a diagnostic directing declarations to module scope.
  No grammar source change or external grammar publication was needed.
- LSP syntax hints no longer call errors inside complete functions missing bodies.
  Missing-token hints use parser evidence; fallback hints apply only at end of input.
  New range tests cover negotiated UTF-8/UTF-16 positions after emoji comments.
- Import quickfixes now replace from the identifier start even when the cursor is
  inside its name. Removed premature outgoing encoding conversion; the shared wire
  writer converts ranges exactly once. Covered both wire encodings and cursor positions.
- Added 66 incremental-versus-fresh session comparisons across incomplete imports,
  package completion, aliases, constants, imported overlays, Unicode, syntax errors,
  diagnostics, completion and semantic tokens. Existing live disk export-cache tests
  cover edits preserving size/mtime, deletion and recreation without watcher events.
- TAR streaming now takes caller metadata `[]u8`, split into two reusable banks.
  Compacts only live global/local names after each extension, preserving PAX defaults
  without archive-length memory growth. A 128-byte buffer processes 4,000 entries.
  Migrated all repository callers; source I/O errors now survive header/metadata reads.
- Added overlap preflight to Unicode transforms (including work), ZIP extraction and
  stream buffers, TAR buffers, XML namespace entry, and process capture output buffers.
  Boundary fixtures cover unchanged output on rejection, exact capacity, partial UTF-8
  prefixes, work exhaustion, namespace rollback, sticky reader errors, and source errors.
  Explicit capacity, partial-output and borrowed-lifetime rules are documented.
- `--timings` now reports per-invocation parse/AST/sema/IR/LLVM/optimization/emission
  details. Removed the misleading zero-duration build `check` record: build semantic
  checking occurs inside codegen. New benchmark records fresh-process peak RSS and
  raw/median timings for generated module trees and the Unicode SDK fixture.

## Validation

Passed locally; logs and raw benchmark samples are in `build/sdk-hardening/`:

- Compiler/editor/frontend/module/build-plan/interface/binding checks, reproducible
  grammar/editor provenance, and separate C translation-unit builds.
- Static analysis: all 26 compiler C translation units, zero warnings.
- Compiler contracts/diagnostics, 192 typed metamorphic builds, two-million-iteration
  bounded-stack stress, and opt-in phase-reporting contracts.
- Full SDK library gate, including 403,031 official Unicode vectors in debug/release,
  archives, DNS, process capture, native provider contracts, and storage boundaries.
- All project validation; the final stack-buffer TAR example also builds/runs and
  prints the expected archive entry. GPU runtime unavailability is explicitly reported.
- ASan/UBSan compiler runs: 49 LSP contracts, 66 edit/fresh comparisons, all language
  rejection cases, timing contracts, compiler stress, TAR memory stress, and the new
  SDK storage fixture built/executed in debug/release. These are sanitized compiler
  invocations; this does not claim instrumentation of LLVM-generated Dyn executables.
- No new native platform execution or platform test batch was performed.

### Compiler baseline

Three fresh no-cache samples per row, one compiler job, this Linux host. RSS values
include waited-for compiler children and are high-water marks. This is a baseline,
not a claimed speedup or a cross-machine performance guarantee.

| Workload | Mode | Median wall ms | Peak RSS MiB (median) |
| --- | --- | ---: | ---: |
| modules-4-functions-25 | check | 8.2 | 30.4 |
| modules-4-functions-25 | debug | 16.6 | 49.2 |
| modules-4-functions-25 | release | 11.2 | 57.9 |
| modules-20-functions-50 | check | 32.0 | 34.8 |
| modules-20-functions-50 | debug | 81.8 | 60.4 |
| modules-20-functions-50 | release | 41.6 | 64.4 |
| sdk-unicode | check | 311.2 | 92.4 |
| sdk-unicode | debug | 441.6 | 162.3 |
| sdk-unicode | release | 2360.0 | 419.3 |

The Unicode release fixture spends about 938 ms in LLVM
optimization and 1073 ms in emission, versus
1.8 ms in semantic analysis. The measured next optimization
candidate is generated Unicode table/backend cost; these samples do not justify
rewriting arena ownership or adding a speculative compiler allocator abstraction.

## Interface migration and limits

`tar.stream_reader(input, header, metadata)` now accepts a byte slice, replacing the
recent arena-pointer interface. Allocate metadata from an arena or use a stack array.
Each half must fit live global/local path/link names plus the next extension payload.
An empty slice supports ordinary TAR only. Names expire at the next `next_stream`.
No rewinding of shared arenas, hidden allocation, ownership wrapper, or provider
allocator-hook change is introduced.

Local aliases remain unsupported by design in this pass. Generic literals remain
syntax errors, not a deferred feature promise. Native Windows/macOS/AArch64 execution,
watch backends and process-tree cancellation remain outside this scope. Detailed
phase durations are nested in coarse totals and may overlap with parallel workers;
peak RSS is a per-invocation resource high-water mark, not an allocation count.
