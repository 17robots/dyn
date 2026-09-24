# Shared compiler and editor analysis

`compiler/src/frontend.h` exposes `dyn_analyze`. Checking, code generation, and
editor semantic requests use the same syntax diagnostics, AST lowering, and
semantic analysis. Module loading and source composition happen before this
entry point; source maps retain original file locations through rewriting.

Strict analysis stops after invalid syntax or entry declarations. Editor analysis
sets `recover` to retain declarations from incomplete code. `parsed` means a tree
was obtained; only `checked` means analysis completed without errors. Neither an
incomplete AST nor an allocation failure may enter code generation. The caller
owns and frees the AST even when analysis fails.

`DynContext` carries an immutable target and diagnostic policy. Sources copy that
policy by value; diagnostic callbacks and callback data remain borrowed. Semantic
function, return-type, and loop state belong to one analysis invocation. Compiler
C allocations retain explicit C ownership. Dyn arenas remain a standard-library
facility.

## Parsed source and symbol ownership

Loaded sources own immutable Tree-sitter trees for their exact text revision.
`dyn_source_tree` returns an independently releasable tree reference. Import
extraction, validation, rewriting, interface extraction, and reflection detection
share those trees. Rewriting and overlay replacement invalidate the old revision;
open-buffer overlays can reuse the editor's current tree. A retained tree remains
valid after its source owner is released. Source bytes remain separately owned.

Global/function name indexes belong to one semantic analysis invocation. Lookup
still checks original module visibility and preserves declaration order for
invalid duplicate declarations. Local lookup starts at the current function's
local range; inactive bindings still participate in the existing no-shadowing
rule. Functions with fewer than 32 locals retain allocation-free linear lookup;
larger functions index appended locals lazily and discard that index at the
function boundary. Active lookup and duplicate detection share the index while
preserving first-declaration order. Index allocation failure follows the
frontend's normal failure path.

Import validation and symbol qualification share `dyn_scope.h`. Each source pass
builds sorted name/visibility intervals once, then queries whether a binding is
visible without scanning preceding statements. Prefix maximum ends handle repeated
names across sibling scopes. Index names borrow that pass's source bytes, and no
index survives a text rewrite. Recovery trees retain ancestor-based lookup.

## Editor cache

Each language-server instance owns a bounded LRU cache of four project analysis
snapshots. Sources larger than 8 MiB still analyze but are not retained. Snapshots
own the merged source, typed AST, and collected diagnostics. Publication and
semantic editor requests reuse the same analysis. Retained views survive eviction; the last
reference frees both. Cache insertion transfers ownership only after all setup
succeeds. Cached sources never retain a request's diagnostic callback or data.

A cache entry represents one root's complete dependency graph. It is reused when:

- Relevant open-buffer content is unchanged (a new version with identical text can reuse it).
- Every dependency directory has the same `.dyn` files and `dyn.project` metadata
  (device, inode, size, nanosecond modification and change times).
- Server configuration has not invalidated the cache.

Imported buffer edits, closes, source additions/removals, and on-disk edits
invalidate affected graphs on the next lookup. Unrelated buffers and non-source
output files do not. Buffer content hashes are computed once per accepted edit.
The cache retains file inventories while directory metadata is unchanged, avoiding
repeated enumeration and path allocations. File metadata is still checked on
every lookup, even without watcher notifications. A directory change triggers a
rescan. Speculative completion patches bypass retention. This is
project-level reuse, not incremental typechecking of individual functions.
Filesystem metadata validation is not an atomic snapshot of concurrent external
writes; subsequent requests observe changes through the next validation.

Diagnostic publication additionally caches checked module ASTs. Each module is
analyzed with its own implementation and canonical interfaces of its transitive
imports. Freshly loaded disk bytes and current overlays are composed before exact
text/source-map comparison; unchanged modules retain their results. Public
interface changes recheck affected importers. Errors or unsupported interface
extraction fall back to the complete project analysis. Cross-module navigation,
references and rename still use a complete project AST.

The module cache retains at most 64 snapshots and 16 MiB of source/map text, plus
AST, syntax and metadata overhead. Allocation failures leave ownership with the
caller; retained snapshots survive eviction. This is module-level reuse, not
incremental typechecking inside a changed function.

Consecutive queued `didChange` notifications coalesce before diagnostic work.
Every edit is applied in order; requests and other messages end the batch.
Partial protocol frames never block publication of an already completed edit.
This avoids processing obsolete queued revisions without introducing worker
threads or asynchronous cancellation.

Set `DYN_LSP_ANALYSIS_STATS=1` to print cache hit/miss counts to stderr on shutdown.
`python3 benchmarks/lsp-analysis.py` measures cold and repeated hover requests,
including process startup and initial diagnostics, on a 300-function dependency.

## Editor implementation

The editor is split by responsibility, with shared internal declarations in
`lsp_internal.h`:

- `lsp_server.c`: protocol dispatch, JSON helpers, wire state/serialization.
- `lsp_document.c`: documents, edits, paths, imports, syntax diagnostics.
- `lsp_analysis.c`: project snapshots, diagnostics, usage/binding analysis.
- `lsp_completion.c`: package, member, local, and expected-type completion.
- `lsp_navigation.c`: symbols, locations, references, hover, tokens, call hierarchy.
- `lsp_actions.c`: code actions and editor formatting.
- `tooling.c`: CLI formatting and documentation; formatting shares
  `dyn_format_source` with the editor.

These are independently compiled C files. Source-level reflection detection uses
`typeof` syntax nodes; comments and strings cannot activate its prelude. Editor
diagnostics are no longer suppressed by matching import-like text on a line.

## Measurements

`python3 benchmarks/frontend-work.py` measures three fresh `--no-cache` object
builds, three linked builds, and twenty serialized edits against a 300-function
imported module. “Cold” disables compiler artifact caching; it does not flush OS
file caches. Edit timing waits for a document-symbol response after the edit,
so it includes all diagnostic publications, not only the initial syntax-clear
notification. The same fixture and harness can run against a saved compiler via
`DYN=/path/to/dyn`. Report cold object and linked-build times separately.

## Regression checks

`just test-contracts` includes concurrent and reentrant frontend analysis,
allocation-failure enumeration for project loading, AST/IR/backend construction,
and cache insertion/lookup. Existing compiler, SDK, and headless Neovim gates run
alongside these checks.

`just fuzz-c` runs grammar smoke cases plus a seeded compiler/editor differential
harness. Each mutation runs compiler check and build, then both incremental and
full-text LSP edits. Diagnostics, symbols, and semantic tokens must agree; repaired
source must recover. Seeds and failing edit sequences are retained in
`build/frontend-fuzz/failure-<seed>.json`.

Use `DYN_FUZZ_SEED=29 python3 tests/frontend-fuzz.py` for another deterministic
sequence, or set `DYN` to a sanitized compiler. `DYN_FUZZ_CASES` controls mutations.
These bounded checks expose regressions; they do not prove absence of other bugs.

## Source and metadata preparation

Merging sources can seed Tree-sitter with the largest prepared file (at least
4 KiB), applying prefix/suffix insertions before incremental parsing. The merged
source owns its new tree; input trees stay immutable. This preserves reusable
subtrees in large constant tables while still parsing boundaries and surrounding
files. Recovery and source-map behavior use the same canonical frontend.

Scope indexing skips expressions, which cannot introduce scopes. Target filtering
first rejects files without the `#target` substring; the existing comment/string
aware scanner handles every possible directive.

Type, alias, field and enum-variant name indexes share an append-only lookup
implementation. Collections under 32 entries keep linear lookup. Larger ones
index names, retain declaration-order and module-ownership checks, and release
storage with the owning AST. Allocation failures mark analysis incomplete.

The LSP additionally retains canonical interface payloads keyed by exact ordered
rewritten file paths, length-delimited contents, and target. The cache is capped
at 64 entries and 8 MiB of key/payload bytes, plus entry overhead. Project loading
still reads disk and applies overlays before lookup; watcher events and mtimes
are not trusted as content identity. Failed cache allocations fall back to
uncached interface generation. `DYN_LSP_ANALYSIS_STATS=1` includes interface
hit/miss counts.

Code generation indexes original-source line starts and local declaration
statements once per debug/tracing pass. Debugger locations retain the original
source-map translation. Protected calls lazily allocate one entry-block unwind
frame per function; loop calls reuse that slot. Optimization levels and debug
information remain unchanged.

Build plans execute directly with one worker. Multiple workers claim jobs from
a shared lock-free atomic cursor where supported, with round-robin fallback
otherwise. Results and error selection remain in source order; worker failures
and interrupted waits retain their existing handling.
