> Historical validation record. Current limits and release status: [readiness](release/readiness.md). The old 32-document LSP limit below was removed.

# Compiler, editor, and SDK correctness audit

Date: 2026-09-20. Self-hosting remains deferred. This records the completed
reproduced-issue pass over the C compiler, runtime, LSP, SDK, and example projects;
it is not a claim that arbitrary programs cannot expose further bugs. No Git
metadata is present in this workspace, so changes have not been committed.

## Reproduced and fixed

| Area | Failure | Regression coverage |
| --- | --- | --- |
| LSP transport | Legal JSON whitespace prevents request dispatch | `tests/lsp-contracts.py` |
| LSP transport | Unicode escapes silently drop document updates | Unicode and surrogate-pair source text |
| LSP edits | Only the first change in a batched notification is applied | Declaration/use rename in one notification |
| LSP overlays | Unsaved sibling declarations are omitted; closing them leaves stale diagnostics | Unsaved open/close lifecycle |
| LSP lifetime | References request for an unopened document crashes | Missing-document request |
| LSP diagnostics | Libraries without `main.dyn` or `module.dyn` are checked without their imports | CLI/LSP agreement on `library.dyn` |
| LSP diagnostics | Completion leaks speculative import errors to stderr | Missing import plus incomplete member completion |
| LSP diagnostics | An unopened sibling's use of a function is ignored | Sibling declaration/use fixture |
| LSP diagnostics | Hundreds of unused constants overflow the response buffer and crash | 400 declarations; bounded diagnostic output |
| LSP hover | Same-named declarations in unrelated projects contaminate hover | Two projects with different `Item` definitions |
| LSP hover | Rewritten import names leak into struct field display | Existing imported `Writer` fixture |
| Highlighting | Constant declarations have competing variable/type captures | `tests/highlights.c` validates three editor queries |
| Highlighting | Constant references lack readonly metadata | Semantic token declaration/reference test |
| Highlighting | Helix queries reference obsolete grammar nodes | All highlight queries compile against current parser |
| Import grammar | Optional alias greedily consumes the following global name | Direct parser cases for inferred/typed/const globals, comments and explicit aliases; CLI/LSP grammar synchronized |
| Imports | An imported function's name makes a same-named object field look like an unknown import alias | `tests/import-field-collision` |
| Diagnostics | Unknown qualifier produces dependent field/call errors | Exactly one root error |
| Runtime trace | Imported/merged files produce wrong file names and huge line numbers | Original helper/main file and function line |
| Cache | Optional cache-file open failure dereferences NULL | `tests/cache-failure.c` |
| Cache | Failed input read leaks the output file descriptor | Descriptor count before/after failed copy |
| Build | Native-library matching silently truncates names and blocks optimized sanitizer compilation | Strict normal and sanitizer builds |
| Binding generator | Named typedef struct absorbs following declaration and emits invalid bindings | `tests/bind-named.py` and fuzz-generated headers |
| SDK | Three collections share one module and collide on declarations | Separate `container/bit_set`, `container/ring`, `container/slot_map` modules |
| SDK | SQLite/SDL raw bindings use obsolete `cabi` alias | Whole SDK checking |
| SDK | Vulkan wrapper calls removed `procedure_into` | Whole SDK checking |
| Projects | Five vendor examples call old arena-taking interfaces | Current buffer-taking interfaces, project validation |
| I/O | Zero-progress read is reported as EOF | `tests/stdlib-contracts` |
| Formatting | Unsupported values silently print `<value>` | Explicit failure for buffer/stream formatting |
| JSON | Arena exhaustion is reported as a syntax error | Capacity versus syntax, with rollback |
| Formatting | Mutable byte slices are not formatted as bytes | Mutable slice test |
| C allocations | Failed declaration-text allocation loses a successful realloc result in two interface builders | `tests/interface-allocation.c`, including forced moving reallocations |
| C allocations | Nested global-initializer failure leaks traversal state and can invent a cycle | `tests/global-allocation.c` |
| C allocations | Case-arm temporary allocation failure crashes lowering | `tests/ast-allocation.c` |
| Parallel builds | Interrupted `waitpid` reports failure and leaves a worker unreaped | `tests/build-plan.c`, injected EINTR |
| Source loading | Short reads are accepted; seek and path-allocation failures are unchecked | `tests/source-failure.c` |
| Target selection | `#target` inside comments or strings silently excludes a file | Three build regressions in `tests/compiler-contracts.py` |
| LSP diagnostics | Opening a sibling replaces syntax errors with inconsistent semantic/unused messages | `tests/lsp-contracts.py` |
| LSP performance | Every unused-name check reloads and reparses unopened siblings | One binding index and qualified-import index per publication; `benchmarks/lsp-warnings.py` |

| Module scope | `check` rejects imported locals that collide with root globals; imports can see root types without `use` | Module scope and type isolation regressions in `tests/compiler-contracts.py` |
| Diagnostics | Unknown parameter/return types produce downstream mismatches without a root diagnostic | Signature validation; invalid target types do not produce argument mismatch cascades |
| Diagnostics | Global initializer cycles go to stderr instead of the editor, with merged locations | Mapped cycle regression in `tests/lsp-contracts.py` |
| LSP warnings | Other functions' locals and same-named fields hide unused bindings; ordinary locals hide unused imports | Resolved AST bindings and qualified import references |
| LSP positions | UTF-8 is advertised without negotiation; UTF-16 edits, tokens, diagnostics, and cross-file rename use byte columns | Default UTF-16, negotiated UTF-8, emoji edit/rename/token/folding coverage |
| LSP JSON | Reordered range keys discard edits; malformed messages and string/negative IDs are mishandled | Structural traversal, Unicode/key validation, bounded nesting, exact ID echo, recovery tests |
| LSP paths | Percent-encoded file URIs fail to resolve sibling modules | Encoded directory with an unopened sibling |
| LSP responses | Oversized completion can advance a cursor past its buffer | Checked response appends and explicit capacity errors; large completion under ASan |
| LSP highlights | Same-spelled locals in unrelated functions highlight together | Shared resolved-origin lookup; scoped highlight regression |
| LSP rename/navigation | Imported symbols use mangled lengths or omit imported type definitions | Original-token ranges for rename, references, type navigation, and call hierarchy |
| Buffered I/O | Zero-sized buffering bypasses zero-progress/error normalization | Empty-buffer contract test in debug/release |
| LSP selection | Only the first requested selection range is returned | Two-position regression |
| Debug info | Merged files produce incorrect DWARF file/line locations | `tests/debug-multifile.py`: original helper breakpoint, local value, caller frame, globals, and struct types |
| Terminal I/O | A later write error loses already transferred bytes | Nonblocking pipe with fixed capacity in `tests/terminal-progress.py` |
| Decimal conversion | Repeated floating-point scaling rounds ordinary decimals incorrectly | 267 exact-bit differential cases, ties, subnormals, overflow, long inputs; debug/release |
| Cache | Partial read failures produce usable hashes and retry a failed stream | Injected partial read/error, zero-key propagation, invalid digest rejection |
| Module allocations | A failed alias copy leaks its successful sibling allocation | `tests/module-rewrite-allocation.c` |

## Follow-up: import and comment boundaries

The follow-up pass reproduced and fixed these additional defects:

- Comments between `use`, its path, and its alias were treated as positional
  operands. Imports now expose named `path` and `alias` fields shared by the
  resolver, rewrite pass, and LSP.
- The obsolete line-based default-alias rewrite rejected multiline aliases.
  It has been removed now that the grammar resolves import/global ambiguity.
- A 200-character default import alias overwrote the LSP's syntax-node storage
  and crashed. Alias storage and copies now respect the supported path bound.
- Unused-import actions depended on compact JSON and deleted entire lines.
  Diagnostic fields are parsed structurally and edits remove the syntax node,
  preserving adjacent declarations and handling tabs/multiline aliases.
- AST lowering treated comments as operands, arguments, and array elements.
  Positional access skips extras; list traversal skips them in a single pass.
- Raw character scans treated `c` inside pointer/slice comments as `const`.
  Qualifiers and function-type delimiters now come from syntax tokens.

Regression coverage includes `tests/compiler-contracts.py` (ten tests) and
`tests/lsp-contracts.py` (34 tests), including execution checks for commented
expressions, calls, arrays, indexing, branches, pointers, and slices. The local
Zed grammar and generated parser have been refreshed.

Current logs: `build/audit-followup-full.log`,
`build/audit-followup-sanitize-build.log`,
`build/audit-followup-compiler-sanitize.log`,
`build/audit-followup-lsp-sanitize.log`, `build/audit-followup-fuzz.log`,
`build/audit-followup-static.json`, and `build/audit-projects-current.log`.
The project validator checks every shipped Dyn module and builds all top-level
projects; host-supported integration checks passed. GPU and interactive-window
limitations remain as described below.

## Follow-up: autocomplete

Completion now reads declarations from syntax nodes instead of line prefixes.
This restores global variables, commented declarations, and multiple declarations
on one line. Imported aliases are also offered as completion items. Function
signature/snippet strings are JSON-escaped before serialization.

Module declaration discovery includes unopened sibling files, respects module
boundaries, and takes open buffers ahead of disk contents for imported modules.
Import-path completion accepts tabs, repeated spaces, and block comments after
`use`. Receiver recovery preserves nested access and function calls inside
incomplete conditions, and handles member access following another inline block.
Function-call receivers stay in member-completion mode rather than producing
unrelated keyword suggestions. An unfinished import also exposed a null-array
`qsort` call when loading an empty module; sorting now requires at least two
sources, with an ASan/UBSan empty-directory regression.

Five new focused regressions cover these failures (42 LSP contract tests total),
in addition to the existing completion suite. Validation logs:
`build/audit-completion-full.log`, `build/audit-completion-sanitize.log`,
`build/audit-completion-sanitize-build.log`, and
`build/audit-completion-static.log`. Interactive editor behavior still requires
restarting the language server and checking the user's exact editing sequence.

The exact `use "` typing sequence now has a regression, including incremental
edits, quote-triggered completion, and an auto-inserted closing quote. Both return
`std` and `vendor` suggestions. The paired-quote case exposed an empty import
resolving to the current module; empty paths now fail resolution instead of
reporting a cyclic import.

The user's editor is Neovim, not Zed. Replaying typing with Neovim 0.12.5's
built-in completion reproduced a server crash: semantic-token requests while
`use "s` was unfinished passed a recovered short string node to import loading.
Removing presumed quotes underflowed its byte length and caused a heap overread.
Import text extraction now validates node bounds and actual quotes, and missing
paths fail safely. The real Neovim typing sequence now completes `std/` and
`std/net/` automatically without manually invoking completion.

`tests/nvim-completion.lua` exercises Neovim's real incremental edits, automatic
completion, and semantic-token requests. It fails against the pre-fix sanitized
server and passes with the fix. `test-editor` runs it when a supported Neovim is
available. A protocol regression also checks every intermediate import prefix
with semantic-token requests before asking for packages. Logs:
`build/audit-nvim-full.log`, `build/audit-nvim-sanitize.log`.

## Memory and SDK decisions

Dyn-owned heap allocation goes through fixed or growing arenas in `std/mem`.
`std/mem.Arena` borrows fixed storage and never silently grows. Caller slices can
use stack or arena backing. C compiler/LSP allocations remain C allocations;
LLVM and Tree-sitter objects retain their provider-specific destruction rules.
See [memory.md](memory.md).

Owned arenas have fallible construction/release. Growing arenas retain stable
allocation addresses, reuse blocks on reset, and release their owned mappings.
Retained input views remain distinct from arena-owned output. Resources still
need explicit close/join/destroy operations.

Domain results intentionally retain their own data and errors; stream adapters
use `io.Result { transferred, error, status }`. A universal untyped result or
raw-pointer generic collection layer would erase useful contracts. Existing
collection modules keep caller storage; future typed maps/arrays/interning should
follow actual Dyn consumers. Neither that future work nor self-hosting is required
for the current C compiler.

Legacy runtime fixtures have been migrated without dropping their behavioral
assertions or reintroducing duplicate compatibility packages. The runtime,
package, CLI, and idiomatic-language guides now use current module/arena APIs.
Decimal parsing rounds to nearest binary64 with ties to even; formatting remains
an explicitly bounded-precision API rather than a shortest-round-trip printer.
Temporary-path generation only proposes a name; reserve it atomically before use.

## Static-analysis triage

The follow-up scan covers all 17 C sources: `build/audit-followup-static.json`.
Cache stream reports were real failure-handling defects and now have fault tests.
The code-generation zero-block report is handled by an explicit empty-CFG guard.
Dead stores in tooling were removed. Build-plan analysis loses the invariant that
`count` advances only when `jobs[count]` is initialized; the read is bounded by
that count, so its remaining uninitialized-job report is a false positive.
`tests/build-plan.c` exercises grouped sources, worker counts, and interrupted waits.

The URI decoder's conservative uninitialized-storage report was eliminated by
bounded initialized decoding storage. Identifier lookup also rejects missing text.
The final tooling scan has no outstanding report; the build-plan invariant report
above is the only remaining analyzer warning.

## Verification

- `just test-c`: full compiler/runtime/SDK gate, build plans, interfaces, bindings,
  highlight queries, 42 focused LSP regressions, ten compiler regressions,
  C fault tests, owned arenas, stream boundaries, exact decimal conversion,
  long environment reads, terminal progress, and multi-file GDB regression.
- `just per-file`: strict C compilation independently of the unity build.
- ASan/UBSan with leak checking: focused compiler/LSP regressions, 107 SDK/project
  modules, 119 LSP project/SDK files, seven C allocation/read-failure executables,
  and 256 fuzz cases.
- `projects/validate.sh`: module checks and supported integrations; SQLite and SDL
  audio execute successfully. The GPU probe reports unavailable on this host.
- Arena and SDK boundary fixtures run in debug/release. macOS and Windows owned
  arena fixtures cross-link; a native guard-page harness checks Windows stack-probe
  page coverage and register/stack preservation. AArch64 networking is compile-tested.

`benchmarks/lsp-warnings.py` reports about 81 ms median for 100 constants and
1,000 unopened sibling functions, including startup/checking and 100 warnings.
The pre-optimization baseline was about 316 ms. The resolved-binding pass does
more work than the earlier lexical-only index; these are fixture measurements,
not a compiler-wide speedup claim.

Logs: `build/audit-final-full.log`, `build/audit-final-strict.log`,
`build/audit-final-lsp-sanitize.log`, `build/audit-final-compiler-sanitize.log`,
`build/audit-final-modules-sanitize.log`, `build/audit-final-project-lsp-sanitize.log`,
`build/audit-final-fault-sanitize.log`, `build/audit-final-fuzz.log`,
`build/audit-final-projects.log`, and `build/audit-final-warning-benchmark.json`.

## Environment limits

Native macOS/Windows/AArch64 execution and interactive editor rendering were not
available on this Linux x86-64 host. Cross-link, query-compilation, and protocol
checks cover the available seams, but cannot certify those native/GUI behaviors.
The local Zed grammar was rebuilt; no remote extension release was published.

The LSP remains bounded (32 open documents, 1 MiB decoded document text, 16 MiB
messages, and bounded result builders). Oversized request results fail explicitly
rather than overrunning buffers. Protocol work follows the
[LSP 3.17 position contract](https://microsoft.github.io/language-server-protocol/specifications/lsp/3.17/specification/#position).

Nested import completion was also checked through incremental edits and slash-triggered requests for `std/`, `std/bytes/`, `std/net/`, `std/net/http/`, and `std/encoding/`. Expected packages are returned, including without `DYN_SDK` set. The Neovim typing and automatic-popup path is covered by the editor-level regression above.

Import path completions insert only the selected segment (`std`, `encoding`, `.`, etc.), never a trailing slash. Typing `/` explicitly triggers the next package list. Completion protocol and Neovim regression checks cover this behavior.

## Compiler consolidation

Compiler and editor consumers now share `compiler/src/dyn_syntax.h` for parser
setup, comment-free operands, declaration names/kinds/visibility, and bounded
syntax text extraction. AST lowering, module rewriting, interface extraction,
completion, fallback navigation, and symbol discovery use these helpers instead
of maintaining separate interpretations. Document/workspace symbols and public
import discovery use syntax declarations, so comments do not invent symbols and
multiline declarations remain discoverable. Speculative editor file reads share
one bounded reader with consistent failure cleanup.

Source diagnostics from checking, lowering, semantic analysis, and import
validation use `dyn_diagnostic_source` to map source ranges through one path.
The whole-program AST is named `DynAstProgram`, with matching destruction API.
Unsupported LLVM constant-expression operations explicitly select runtime
initialization; fake LLVM API aliases have been removed. Handwritten compiler C
is formatted consistently, with its style recorded in `compiler/src/.clang-format`.

Sanitizer validation also found leaked automatically resolved native-library
paths. Command execution now returns through one ownership boundary that frees
these paths, including cache hits and failures, while preserving borrowed CLI
arguments. Regression coverage exercises fresh builds, cache hits, compiler
errors, and partial native-library discovery failures.

The follow-up consolidation adds shared frontend analysis and a bounded
language-server analysis cache; see [frontend ownership and cache behavior](frontend.md).
C allocation remains ordinary C ownership; Dyn arena policy remains in the Dyn
standard library.

Validation: `just all per-file test-c` and `just sanitize-test-c` passed, plus
sanitized compiler contracts (11 tests) and LSP contracts (44 tests). The editor
gate includes headless Neovim import completion. Logs are
`build/cleanup-final-tests.log`, `build/cleanup-sanitize.log`,
`build/cleanup-sanitize-compiler.log`, and `build/cleanup-sanitize-lsp.log`.


## Shared frontend follow-up

Checking, code generation, and editor semantic analysis now enter through
`dyn_analyze`. Target/diagnostic policy and semantic function/loop state are
explicit per analysis, including reentrant diagnostic callbacks. Editor analysis
retains incomplete declarations without allowing failed analysis into codegen.

The LSP caches dependency-aware project snapshots, invalidated by relevant buffer
versions, source membership, disk metadata, or configuration changes. Retained
views survive eviction. Struct-fill actions, enum expected types, parameter
snippets, field hovers, imported declaration hovers, and public documentation use
syntax/semantic structure, including multiline declarations and comments.

New fault-injection and fuzz cases found and fixed:

- Partially allocated source maps leaking on merge failure.
- Partially allocated AST statements, IR tables, and backend metadata reaching
  consumers or cleanup with invalid indices/pointers.
- Import-name allocation failures causing NULL dereferences or silently skipping
  required symbol rewrites; failed manifest-name allocation leaking its root.
- Unknown local types returning an error type without a diagnostic, allowing
  `fn main() { alias:r }` to reach code generation with no local slot.
- Cyclic imports bypassing editor diagnostic collection instead of reporting at
  the importing `use` statement.
- Comments between `struct` and its name incorrectly selecting packed layout.

Allocation-failure coverage includes project loading/composition, frontend,
IR/backend, and cache ownership. Seeded differential fuzzing compares compiler
check/build plus incremental and full-text editor diagnostics, symbols, and
semantic tokens. See `docs/frontend.md` for reproduction commands and limits.


Validation: `just all per-file test-c`, `just sanitize-test-c`, and `just fuzz-c`
passed. Additional frontend fuzz seed 29 passed normally and under ASan/UBSan; all 13
compiler contracts also passed under sanitizers. The suite includes 47 LSP
contracts, 13 compiler contracts, 107 SDK module checks, 119 project/SDK LSP files,
and headless Neovim completion. Allocation tests now run through `test-frontend`,
including from the sanitizer gate.

On the 300-function imported-project fixture, 30 hover requests including startup
and diagnostics improved from about 236 ms to 29 ms median; one request improved
from about 37 ms to 26 ms. These are whole-server fixture measurements, not a
compiler-wide speedup claim. Raw samples are in
`build/frontend-benchmark-before.json` and `build/frontend-benchmark-final.json`.

Logs: `build/frontend-final-full.log`, `build/frontend-final-sanitize.log`,
`build/frontend-final-targeted.log`, `build/frontend-final-fault-sanitize.log`,
`build/frontend-final-fuzz.log`, `build/frontend-fuzz-29.log`,
`build/frontend-final-compiler-sanitize.log`, and
`build/frontend-final-fuzz-sanitize.log`.


## Efficiency and editor-module follow-up

Loaded sources now retain syntax trees across import discovery, validation,
rewriting, and interface extraction. Copies retain independent tree references;
text replacement invalidates the old revision. Reflection uses actual `typeof`
syntax nodes, so comments and strings cannot inject reflection declarations.

Diagnostic publication now uses the same cached project analysis as hover and
other semantic requests. Cached diagnostics own their messages and never retain a
callback. Cache hits reuse precomputed buffer hashes and file inventories; file
metadata remains checked on every request to cover missing watcher events.
Semantic function/global lookup uses invocation-owned name indexes, with module
visibility checks preserved. Local searches stay within the current function.

The former 5,700-line `tooling.c` is split into independently compiled editor
modules for server, documents, analysis, completion, navigation, and actions.
CLI formatting/documentation remain in `tooling.c`. Byte-scanning import
suppression has been removed from diagnostic publication.

Regression coverage adds cached diagnostic reuse, allocation-free cache hits,
prehashed-buffer invalidation, retained source-tree lifetime, and reflection-like
comments/strings. Existing fault injection also covers the new name indexes and
cache inventories. See [frontend design](frontend.md) for ownership details and
benchmark methodology.

Measured on the same 300-function imported-module fixture (compiler artifact
cache disabled; OS caches uncontrolled):

| Measurement | Before | After |
| --- | ---: | ---: |
| Cold object build | 49.3 ms | 40.1 ms |
| Cold linked build | 48.7 ms | 45.4 ms |
| Edit through diagnostic publication | 27.5 ms | 10.6 ms |

These are fixture measurements, not universal speedups. Raw samples:
`build/efficiency-before.json`, `build/efficiency-after.json`. Syntax trees now
remain alive across project passes, trading a longer tree lifetime for avoiding
repeated parsing; source copies share tree storage through Tree-sitter references.

Validation passed: `just all per-file test-c`, `just sanitize-test-c`, and
`just fuzz-c`; separately, 14 compiler contracts and frontend fuzz seed 29 passed
under ASan/UBSan. The full suite includes 48 LSP contracts, headless Neovim,
107 SDK/project modules, and 119 project/SDK LSP files.
Logs: `build/efficiency-final-full.log`, `build/efficiency-sanitize.log`,
`build/efficiency-fuzz.log`, `build/efficiency-compiler-sanitize.log`, and
`build/efficiency-fuzz-sanitize.log`.

## Library contract cleanup

Canonical I/O entry points now normalize callback results; redundant public aliases
and SDK dependency manifests pointing at the removed `sdk/` tree are gone. SQLite
failed-open cleanup, zstd byte counts/arena rollback/exact-capacity decoding, buffered
writer partial failures, and OpenSSL crypto failure counts have regression coverage.
TLS constructors share provider setup and cleanup; SSL error classification happens
before other provider calls, queues are cleared before operations, and clean EOF and
malformed ALPN have deterministic tests. See [migration contracts](library-migrations.md).

Compiler regressions fixed: enum-alias variant lookup, reflection ABI propagation
through separate-module interfaces, and public entry points misdiagnosed when compiling
dependencies. Directly proven local-storage return escapes are diagnosed, with borrowed
parameters and static reflection metadata preserved. This is not a borrow checker.

Passed locally: `just all per-file test-c`, `just sanitize-test-c`, 17 compiler contracts
under ASan/UBSan, all 22 SDK fixtures in debug/release with normal and sanitized compilers,
`projects/validate.sh`, and fuzz smoke. Sanitizing the compiler does not instrument the
emitted Dyn programs or external provider libraries. SDL3 audio passed; GPU execution
reported unavailable. Native Windows/macOS arena and Ubuntu provider-version jobs are
configured but have not been run from this session.

Logs: `build/library-full.log`, `build/library-sanitize.log`,
`build/library-compiler-sanitize.log`, `build/library-contracts.log`,
`build/library-provider-sanitize.log`, `build/library-projects.log`,
and `build/library-fuzz.log`.

## Six-part SDK follow-up

Fixed conflicting scratch selection and typed short-option values. Removed the three
redundant arena aliases and migrated callers, including the arena benchmark. Allocation
and subarena results now distinguish meaningful failure cases and valid empty results.

Core buffer contracts cover strings, C conversion, flags text, and byte codecs. Arena string
conveniences share caller-buffer operations; error cases preserve prior allocations. Codec
validation precedes writes. Base32 exact-capacity decoding, interior padding, and size overflow
are covered, as are empty arena-backed strings. See [buffer contracts](buffer-contracts.md).

Added provider-owned SQLite statements with copied bindings, typed borrowed columns and
explicit execution/reset/finalization state. Added a byte/string builder with explicit arena
growth and a string-keyed integer map with transactional insertion. The SQLite example uses
bound statements. See [SQLite](sqlite.md) and [collections](collections.md).

Validation passed: `just test-c`, `just test-libraries`, `just sanitize-test-c`, and
`projects/validate.sh`. All 24 SDK fixtures ran in debug/release; 69 deterministic codec
inputs matched Python's standard hex/Base32/Base64 implementations. The SDK/reference cases
and 18 compiler contracts also passed using the ASan/UBSan compiler. The full gate checked
110 SDK/project modules, 48 LSP contracts, Neovim completion, and 123 SDK/project LSP files.
Sanitized compiler runs do not instrument emitted Dyn code or native provider libraries.
SDL3 GPU execution remains unavailable on this host; SDL3 audio passed.

Logs: `build/sdk-six-full.log`, `build/sdk-six-libraries.log`, `build/sdk-six-projects.log`,
`build/sdk-six-sanitize.log`, `build/sdk-six-libraries-sanitize.log`, and
`build/sdk-six-compiler-sanitize.log`.
