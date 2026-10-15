# Dyn bootstrap compiler

## Bootstrap architecture

Dyn uses a thin vertical slice from source to native executable:

```text
module directory -> source manager -> handwritten parser -> owned AST -> semantic checks
                 -> typed IR -> LLVM C ABI -> ELF object -> linker -> executable
```

Executable targets are `x86_64-linux`, `aarch64-linux`, `aarch64-macos`, and
`x86_64-windows`. Cross-linking macOS uses `zig` (its bundled Mach-O linker),
while Windows uses GNU `ld`'s `i386pep` backend; neither output is executed by
the Linux test host. `--no-link` emits Mach-O arm64 and COFF x64 objects.
Cross-target smoke programs also compile and link `std/os/windows` and `std/os/macos`: Windows x64
provides Win32 file/page-memory/thread, Winsock socket, and `WSAPoll` adapters;
macOS arm64 provides Darwin file/page-memory/socket/poll/thread adapters.
Cross-linked artifacts are format- and unresolved-symbol-checked on Linux; the
release workflow runs them on native macOS, Windows and Linux AArch64 runners.
`--target` rejects every other value before code generation. Backend
uses that explicit triple rather than host default, so cross-host execution
cannot silently produce an object for the wrong architecture. Runtime object,
syscall ABI, ELF linker policy, and dynamic-loader path remain target-specific;
other targets require their own runtime/platform implementation. Linux AArch64
emits native ELF objects; execution tests require AArch64 hardware or an external
emulator. `#syscall` uses portable Linux IDs (matching x86-64); constant IDs with
argument-compatible AArch64 calls are translated during checking. Dynamic or
unmapped IDs are rejected, preventing x86-64-only calls from silently
using wrong kernel operations.

Target identity and capabilities (`arch`, `kernel`, ABI, libc boundary,
endianness, and pointer width) live in one compiler descriptor. Both `--target`
and `#target` consume it. Only targets supplying tested startup runtime, linker
policy, ABI layouts, and platform stdlib are executable targets.

The implemented front end covers functions, primitives, locals, control flow, structs,
pointers, arrays/slices, enums/case, and the first module/import slice. Integer arithmetic,
division, shifts, pointer access, indexing, and slicing retain runtime safety checks in debug
and release. Bare expressions are not statements; calls receive dedicated statement handling.

Control flow uses compiler-owned statement trees referencing child-statement ID lists. Semantic
analysis enforces boolean conditions, block visibility, forbidden shadowing, valid loop exits,
and unreachable statements. LLVM lowering emits explicit basic blocks for `if`/`else`, condition
or infinite `for`, `break`, `continue`, and returns nested in branches.

Struct declarations become nominal type IDs with ordered field tables and compiler-calculated
size/alignment. Packed structs remove field padding and use alignment 1. LLVM uses named aggregate
types, `insertvalue` construction/update, and `extractvalue` access. Struct locals and assignments
copy aggregate values. Same-directory files share one deterministic declaration namespace.

General-function lowering collects all signatures before any body, then resolves typed calls,
parameters, returns, forward references, and recursion. Each function owns its local-ID range.
LLVM functions are declared as one batch before bodies are emitted.

## Modules

The module loader canonicalizes directory imports, forbids project-root escape, recursively loads
dependencies, and reports complete import cycles. Imports bind an optional alias; imported
functions, structs, and enums require qualified access and `pub`. Qualified function calls,
struct types/literals, enum variants, and payload patterns pass through semantic analysis and
native code generation. Compiler-owned source copies receive stable internal symbols derived from
their canonical module paths before AST construction. Different modules may therefore declare
identical function, struct, and enum names without collisions.
Input limits are explicit: 64 MiB per source, 4096 source files per module, and 256 MiB after
module merge. Oversized input fails before its source buffer is allocated.

## Typed Dyn IR

Typed IR is a deep module at the semantic/backend seam. Its small interface accepts one checked
AST and returns one self-contained `DynIrProgram`; destruction is the only other operation.
Lowering strips source-only names and spans, copies resolved type/local/function/field IDs, and
normalizes compound assignments into ordinary typed expressions. Validation rejects unresolved
types, invalid IDs, malformed child ranges, and non-normalized assignments before LLVM runs.

LLVM lowering consumes only typed IR. Semantic AST is freed before LLVM context creation. This
keeps source-language knowledge local to parsing/sema and backend knowledge local to codegen.

## Globals and initialization

Top-level ordinary variable declarations create mutable zero-initialized storage. Explicit and
inferred types, reads, writes, compound assignments, addressable aggregate access, and imported
`pub` globals flow through AST, semantic analysis, typed IR, and LLVM. `const` declarations require
compiler-evaluable initializers and reject writes. A generated `dyn_init` function evaluates
runtime initializers once before `main`; imported module sources are ordered before importers.
The semantic pass follows direct references and global reads reachable through called functions,
topologically orders initialization, and rejects cycles. Compiler-evaluable scalar, struct, and
array constants are emitted directly as read-only LLVM globals. Runtime work is split into stable
per-module `__dyn_init_*` functions, emitted only for modules that need it and called dependency-first.

Function signatures are structurally interned independently from pointer descriptors. Semantic
analysis resolves `&function`, checks indirect argument/result types, and preserves signature IDs
in typed IR. LLVM lowering emits opaque function-pointer values and typed `call` instructions;
every indirect call receives a non-null guard. Function addresses also participate in static
constant aggregate initialization.

Pointer types are interned nominal descriptors containing pointee type and shallow-const flag.
Typed IR preserves those descriptors while dropping source syntax. Backend lvalue lowering handles
locals, explicit dereference, nested fields, packed fields, and automatic pointer-field access
through one storage-pointer path. Dereference guards validate non-null and pointee alignment before
loads, stores, or field address calculation; guards remain in release builds.

Array and slice types are interned descriptors carried through typed IR. LLVM lowers fixed arrays
to native array aggregates and slices to `{ptr, i64}` values. One indexed lvalue path handles loads,
stores, address-taking, and compound assignments with runtime bounds guards. Range lowering checks
`start <= end <= len`; `for-in` evaluates its collection once and copies each element into the
iteration binding. Pointer iteration bindings remain a later extension.

Enum lowering records nominal variants, backing tag type, maximum payload size/alignment, and final
tagged-union layout. Case analysis normalizes literal/range patterns into disjoint closed intervals,
checks full-domain or variant coverage, and emits branch chains. `_` is always the fallback,
independent of source-arm order.

Defer lowering maintains a lexical cleanup stack during control-flow emission. Block fallthrough,
`return`, `break`, `continue`, explicit `#panic`, and generated safety guards emit active cleanups in
reverse order. Deferred-call operands are evaluated into hidden slots at the defer site; deferred
blocks instead load live local storage at exit. Cleanup code suppresses recursive cleanup if it
panics. Panic checkpoints around calls propagate cleanup through caller frames without allocation;
a second panic aborts remaining cleanup.

Builtin expressions lower directly into typed IR. `#sizeof` and `#alignof` use compiler-owned
layout descriptors and never evaluate value operands. `#cast` emits explicit LLVM numeric or
pointer conversions; `#bitcast` requires equal compatible scalar representations. Linux x86-64
`#syscall` accepts a syscall number plus up to six integer/pointer arguments and calls a tiny
libc-free register-shuffling runtime bridge. `#typeof` resolves operand types without evaluation,
materializes compiler-owned `TypeInfo`, and lowers only used type-name metadata into IR.

Compiler data uses integer IDs into arena-backed arrays. Long-lived source, module, AST,
type, and IR data use a persistent arena. Temporary phase data uses a resettable scratch
arena. The present source loader still uses libc allocation; replacing that with these
arenas is next implementation slice.

Linux x86-64 starts without libc: `dynrt_start.o` defines `_start`, calls generated
`main`, then performs exit syscall. LLVM emits native objects. Linux executables
(x86-64 and AArch64) link in-process (`src/link_elf.c`): relocatable objects and `ar`
archives, lazy archive members, section garbage collection, a GOT for
GOT-relative relocations, and `.eh_frame` records pruned with their code. No
external linker is spawned. Shared libraries and GNU linker scripts (such as
`/usr/lib/libc.so`) are inputs too: the executable becomes dynamic, with
`PT_INTERP`, `.dynamic`, a SysV `.hash`, symbol versions, PLT entries bound
through `JUMP_SLOT` slots at load time (`BIND_NOW`, no lazy PLT), canonical PLT
addresses for imported functions whose address is taken, and copy relocations
for imported data read by non-PIC code. `--shared` output is linked in-process
as well; as with lld, its default-visibility definitions stay preemptible.
macOS arm64 executables and dylibs link in-process too (`src/link_macho.c`):
objects, archives, dylibs and `.tbd` stubs in; out comes a PIE or dylib whose
imports bind at load time through `LC_DYLD_INFO_ONLY` (non-lazy stubs), with
an export trie and the ad-hoc, linker-signed code signature Apple silicon
requires. Debug info stays in the objects and no `__unwind_info` is written.
x86-64 Windows executables and DLLs link in-process too (`src/link_coff.c`):
COFF objects and ar/.lib archives, including short import objects, whose
imports extend the runtime's own `.idata$2..$7` directory; grouped sections
merge in suffix order. Executables keep GNU ld's fixed base; DLLs get base
relocations, an export table of every external definition, and an import
library in `llvm-dlltool`'s layout that both GNU ld and the built-in linker
read. Only Wasm still uses an external linker (`wasm-ld`). `DYN_LINKER=external`
forces the external linker, including its ThinLTO, for differential checks.

Standard-library imports resolve relative to compiler executable, never process working
directory. Initial `std/terminal` and `std/io` are ordinary Dyn over `{data,len}` UTF-8 strings and `#syscall`;
its ABI is documented in [the std ABI](standard-library-abi.md).

`tools/build.py` compiles each source file to its own object in parallel (`JOBS` or `--jobs` sets
the worker count) and relinks only when an object changes. `just per-file` builds a single-command
per-file binary.
The parser is part of the compiler (`src/parser.c`); building needs no grammar
checkout. `just test` runs the regression suite. `just artifact
dyn-sanitize` builds the compiler with ASan and UBSan; CI runs the compiler
contracts and generics tests with it. A minimized regression case belongs in
`tests/` next to the fix.

`--timings` prints load, check, codegen, and link wall time to stderr. `just install`
installs compiler, runtime objects, and standard library under `PREFIX`; `just
package` builds and validates a relocated SDK outside the source tree. Both Linux targets
ship startup/support objects; target seam remains explicit, not a portability claim.
AArch64 Linux executables and shared libraries link in-process too, with
lld's 64 KiB maximum page size and its adrp relaxations (adrp+add to nop+adr
within 1 MiB, GOT adrp+ldr to adrp+add for local symbols), so code matches
`ld.lld` output instruction for instruction. Object and assembly emission
need only LLVM backend. Tests execute through `qemu-aarch64` when available.

## Error boundaries

CLI/environment failures exit 2. Source diagnostics exit 1. Success exits 0. Parser and
semantic passes collect up to 20 reliable errors. Internal assertions never substitute
for user diagnostics.

## Build modes

Debug is default (`O0`). Release gives non-entry definitions internal linkage, runs LLVM's
`default<O2>` pipeline, and removes unreachable whole-program code. Language safety checks remain
enabled in both; release may eliminate a check only when LLVM proves it cannot fail.
Checked add, subtract, and multiply use LLVM overflow intrinsics, preserving traps while exposing
their semantics to optimization passes.
Code generation reuses exact nil/alignment and index facts while the successful guard block
dominates the use. Facts key on LLVM SSA values: an intervening load after any possible aliasing
store is a different value. A branch merge only retains a fact when every incoming path passed its
guard. This small CFG proof is sound in debug builds too; LLVM performs broader dominance/range
optimization in release builds.
Repeated loads from one local slot are equivalent only inside one source statement, where no
intervening statement or call can mutate the slot.
Typed IR performs conservative unsigned loop-range proofs. It removes checked additions only when
an exact induction bound and maximum accumulated value prove overflow impossible, and array bounds
checks only when the inferred unsigned index maximum is below the fixed array length. Nested
control, defer, calls, unknown stores, and possible local aliases invalidate the proof.

`dyn run DIR` builds a temporary executable, runs it without shell mediation, returns its exit
status, and removes the executable. `--no-link` is rejected for `run`. `--emit-asm` writes the
post-optimization target assembly beside other requested build artifacts.
Build output is created through a temporary sibling and atomically renamed.
On x86-64 Linux release builds, separately compiled modules use ThinLTO bitcode.
The compiler runs ThinLTO itself (`src/thinlto.cpp`) with lld's settings for a
static executable: symbols the runtime or `--link` inputs define or use stay
visible, everything else may be internalized, loop and SLP vectorization follow
the optimization level, and backends are cached under the build cache's
`thinlto/` directory with lld's pruning policy. A sample profile's call graph
orders functions with LLVM's cache-directed sort, as lld does by default.
`tests/builtin-linker.py` checks that the code and function order match
`ld.lld`'s. Debug builds always use native objects.

Plain executable builds use a content cache beside output. A versioned input snapshot validates
compiler, target, mode, output, link inputs, module directories, manifests, and transitive sources
before frontend loading. Unchanged builds therefore skip discovery, parsing, code generation, and
linking. Metadata uncertainty falls back to content validation; `--no-cache` forces rebuilding.
Runs and artifact-emitting builds bypass executable cache. Native `run` commands still reuse shared module artifacts: unchanged modules skip machine-code generation, then each invocation links and executes a fresh temporary binary. `--no-cache` disables this reuse.

Compiler fingerprints use the running executable's path, so invoking `dyn` through
`PATH` has the same cache behavior as using its absolute path. Changing the compiler
or source invalidates the corresponding cached artifacts.

Copies from addressable struct and array values use memory-copy intrinsics instead
of materializing every element as an LLVM SSA value. Assignments through a field,
index, or pointer snapshot the source before evaluating the destination, preserving
value semantics even when storage overlaps. This does not eliminate optimization
costs for aggregate expressions, calls, or returns.

`dyn build MODULE --shared --output libname.so` emits a position-independent
ELF shared library on Linux x86-64 or AArch64, a PE DLL on Windows x86-64, or
a Mach-O dylib on macOS AArch64. Public functions and globals are
exported with their Dyn names; private declarations are hidden. The library
contains Dyn's runtime support but no executable startup object. Shared-library
builds bypass the executable cache and cannot be combined with `run` or
`--no-link`. The Linux gate executes a native ELF consumer. It cross-links PE
and Mach-O consumers and inspects their export/import metadata, but does not
execute them; native Windows/macOS CI is still required for runtime validation.
Windows DLL output also writes the GNU-compatible sibling import library
`OUTPUT.a`, which is the link input for cross-target Dyn consumers.

## Tooling and projects

`dyn fmt DIR` performs semantics-preserving canonicalization that only inserts or removes
whitespace: one statement per line, one space after each comma, LF line endings, no trailing
horizontal whitespace, and a final LF. See [style](../guide/style.md). It requires every file to parse
(imports are not resolved) before any atomic replacement and preserves file permissions.
`dyn fmt --check DIR` changes nothing and exits 1 when formatting differs. LSP formatting uses the
same rules, returns only the changed lines, and returns no edits for malformed documents.

`dyn docs DIR` emits Markdown containing public declarations. `dyn lsp` implements bounded
JSON-RPC framing, lifecycle, incremental document synchronization and tree reuse, compiler-backed
diagnostics, hover, completion/snippets, signature help, references, rename, formatting, symbols,
semantic tokens, inferred-type and call-parameter inlay hints, document highlights, folding ranges, selection ranges,
semantic incoming/outgoing call hierarchy,
rename preparation, and cross-document definition.
Open-document storage grows dynamically; each decoded text is limited to 1 MiB and URIs to 64 KiB.
The server performs no filesystem mutation. Typed hover and local/global/field definition lookup query the resolved compiler
AST, so inferred variables report their concrete type. Struct and enum hover summarize members;
function completion includes signatures and positional-argument snippets. Struct literals, enum
variants, typed enum assignments, call arguments, return expressions, locals, loop bindings, and result fields receive
type-directed completion. Results are deduplicated, locals sort before declarations, and unrelated
open packages do not leak private or unqualified public declarations. Imports support
unused-use warnings and quick fixes, nested path/member completion, imported hover, filesystem navigation,
qualified auto-import edits, and unknown-symbol quick fixes that insert `use` and qualify the symbol.
Struct literals offer a rewrite action that inserts absent fields with type-appropriate defaults.
Type-definition navigation follows inferred struct and enum values;
declaration and implementation navigation resolve concrete Dyn declarations.
References and rename use compiler bindings and merged-source origin maps. Functions, locals, globals,
and fields remain distinct even when names match; same-package unopened files and imported package
sources participate without requiring editor buffers. Rewrite origin maps translate qualified imported
members back to their original source positions.
Workspace-symbol queries include unopened files from the workspace root, with open buffers overriding
disk contents. Watched-file, workspace-folder, and configuration changes refresh diagnostics. Merged
compiler sources retain origin maps so diagnostics and navigation report original paths and ranges.

`--diagnostics json` emits source diagnostics as newline-delimited JSON objects with severity,
message, path, and 1-based start/end range. Human diagnostics remain default.

Optional `dyn.project` grants imports access to explicit dependency roots:

```text
dependency utility ../utility
```

`use "utility/submodule"` then resolves below that canonical root. Duplicate names, malformed
lines, missing directories, and traversal outside a declared root are rejected. Without a
manifest, imports remain confined to project root plus `std`.
Compiler emits one object per module for ordinary executable builds. `--jobs N` bounds process
workers; zero defaults to available CPUs. Every worker owns its LLVM context. Dependency symbols are
declarations, owned symbols and module initialization are definitions, and root calls initialization
in deterministic dependency order. Completion order never affects output ordering.

Module objects and interfaces use shared content-addressed storage (`DYN_CACHE_DIR`, then the
platform user cache directory) keyed by compiler bytes, target, mode, module
implementation, and declarations in the module's transitive import dependencies.
Private function-body changes rebuild only their module; declaration changes rebuild
affected importers while retaining unrelated objects. Private types/constants are
included conservatively because public declarations can expose them. Projects using
reflection retain project-wide content dependencies for stable type metadata. Explicit link-input
changes relink without rerunning LLVM. Stored object digests are verified; corruption becomes a miss.
Artifact-emitting and `run` builds retain monolithic codegen because they have different output and
lifetime contracts.
`dyn cache stats` reports shared-cache use; `dyn cache clean` removes shared artifacts.


`dyn docs MODULE_DIRECTORY --json` exports schema-versioned public declarations,
source comments/locations and parsed target gates without an LSP server. It uses
syntax parsing, not semantic validation; private declarations and function bodies
are omitted. See [agent workflow](../guide/agent-guide.md) for query examples and limitations.
