# Compact compiler parser experiment

This experiment implements expressions, types, declarations, statements, imports,
and target/link directives in a handwritten parser. Default Dyn artifacts still
use Tree-sitter throughout. Explicit qualification artifacts link the compact parser for declaration checks
and retained source consumers, with a separate direct AST artifact; see the transitions below. The pinned
Tree-sitter grammar remains the syntax specification and differential oracle.

Run from the compiler repository:

```sh
just test-parser-experiment
python3 tools/parser-experiment/check.py --samples 1000 --sources --corpus std --corpus tests --corpus /path/to/dna
CC=/usr/bin/clang BUILD=build/parser-sanitize python3 tools/parser-experiment/check.py --sanitize --samples 500
python3 tools/parser-experiment/check.py --benchmark
```

The runner needs the same Tree-sitter headers/runtime as the compiler and the
pinned grammar fetched by `just deps`. `CC`, `BUILD`, and `TS_DIR` are honored.
Benchmark and corpus JSON go to `build/parser-experiment-work/` by default.
The default recipe checks std/tests expressions and complete source trees. An
external DNA checkout is optional and must be supplied explicitly.

## Representation and ownership

Nodes are 32 bytes, indexed into a caller-owned reusable array. Nodes retain byte
spans, child/sibling/parent links, operator spans, semantic modifier flags, and
named-field roles. Flags preserve public/packed/distinct/const declarations and
types, pointer iteration, inclusive ranges, primary expressions, bitcasts, and
wildcard case arms. Roles preserve names, external symbols, import paths/aliases,
libraries, array lengths, call arguments, and function-type returns. The latter
replaces reliance on the anonymous closing parenthesis in the current AST reader.
Only reachable nodes receive parent links; discarded speculative nodes may remain
in the allocation and must not be traversed as declarations.
Source bytes are borrowed. Parsing does not perform semantic analysis or escape
decoding. Failed parses never expose a root; callers can reuse or release storage
on every failure path. Type/array ambiguity reuses the parsed bracket contents,
avoiding exponential replay of nested array arguments.

`snapshot.h` adds an opaque immutable source revision for ownership qualification.
It copies source bytes, parses before publication, and exposes const node/text
views. Atomic retain/release keeps independently held references alive after the
original owner releases its reference; reference-count overflow refuses retention.
Creation shares its work budget across copying and parsing and never stores a
callback or its data. The reusable `ExpTree` API remains available for parsing
benchmarks; snapshots intentionally pay for ownership and are not part of those
timings. Snapshot tests cover concurrent readers, independent source lifetime,
every allocation failure, and cancellation during copying and parsing. Published
snapshots shrink node storage to the exact count. Only opt-in artifacts retain
these snapshots in source revisions.

The expression entry point supports scalar and aggregate literals, types/type
arguments, casts, calls, fields, dereference, indexing/slicing, and expression
builtins. The source entry point also covers declarations, statements, generics,
imports, directives, and statement/loop builtins. Syntax acceptance does not imply
semantic validity. Contextual keyword rules follow the pinned parser, including
identifiers that would be keywords in another context.

Both entry points limit recursive parser calls to 256 and share a non-resetting
work budget of `128 * source_bytes + 1024` units. `ExpOptions` can lower the
recursion limit, supply a work limit, and provide an invocation-local cooperative
work callback. Work includes the initial source length, token reads (including
lookahead), bounded long-token scans, and parent/field finalization. Callback
failure stops parsing without publishing a root. Cancellation, allocation,
work/depth limits, and syntax errors have separate error kinds; speculation
preserves resource failures. Tests cancel at every callback, including lookahead,
UTF-8 strings, escape sequences, comments, whitespace, and finalization.
This is an experimental policy, not equivalence to the production 1024-level
syntax-tree depth limit. Byte spans still require source length at most UINT32_MAX. Long
left-associated expressions parse and serialize iteratively. The Tree-sitter
oracle serializer is recursive and is intended for bounded test inputs.

Whitespace follows the pinned generated lexer: ASCII whitespace, not arbitrary
Unicode whitespace. Its external trailing-float scanner rejects vertical tab
before a trailing-dot number; regression coverage preserves that behavior.
Comments do not nest. Source and literal locations remain UTF-8 byte offsets.

## Differential evidence

Tests compare normalized named trees, byte spans, supported operator spans,
association, semantic modifiers, field roles, and acceptance/rejection. Expression
wrappers (`primary`, `expression`, `literal`) and comments are omitted in both
representations; primary context survives as a flag. Extracted direct-call
statements receive an expression-context primary flag only for the isolated
expression comparison; complete-source comparisons preserve statement context.
The wrapped-expression oracle requires exactly one declaration, so additional
source declarations cannot masquerade as trailing expression text.

Coverage includes every binary-operator pair, contextual keyword matrices,
type-versus-expression ambiguities, generated expressions, source fixtures,
seeded deletions and malformed suffixes. `extract-tests.py` reads source-like
Python string literals without executing tests; incomplete and invalid literals
remain oracle rejection probes. Dynamic strings are not evaluated.

`--corpus` extracts expressions in their original Tree-sitter context and records
paths, byte offsets for mismatches, source hashes, invalid files, and mismatch
counts in `corpus.json`. It excludes `.git`, `.jj`, `build`, and `.cache` trees.
`--sources` additionally compares complete normalized source trees. Invalid
corpus files are reported explicitly, and source acceptance differences fail.
Allocation-failure, cancellation, snapshot lifetime, bounded-read, nesting, long-chain, and reuse tests run before
differential tests. Sanitizer crashes or diagnostics cannot count as rejection.

These checks do **not** prove production migration readiness. Semantic metadata
now has explicit representation and differential coverage, and opt-in consumers
have separate semantic qualification gates. Error messages/recovery and accepted depth are not
equivalent to production. Failure diagnostics are deterministic within this
parser; that is not diagnostic parity between parsers. These contracts must be
qualified before a default switch, even when the current corpus passes.

## Measurements

The original scalar workload was 3,767 bytes. On the development host, 1,000
parses took median 0.047 CPU seconds in the experiment versus 0.285 in Tree-sitter
on 2026-10-13. That historical roughly 6x result covers only that expression
workload and predates the complete-expression/source additions.

Before adding 32-byte semantic metadata and cancellable work, the same expression workload measured
0.052367 versus 0.284934 CPU seconds for 1,000 parses (about 5.4x). A complete
29,218-byte `std/encoding/json/json.dyn` file measured 0.024221 versus 0.162163
CPU seconds for 100 parses (about 6.7x), across five alternating samples. The
compact source tree used 5,840 allocated nodes and 196,608 bytes of capacity.
These local results still exclude imports, semantic analysis, and code generation.

With semantic metadata, cancellation, and parent finalization included, the
latest five-sample run measured 0.059401 versus 0.288178 seconds for expressions
(about 4.9x), and 0.028665 versus 0.152800 seconds for the complete source (about
5.3x). Source node count remains 5,840; 32-byte nodes increase retained array
capacity to 262,144 bytes. These measurements exclude immutable snapshot copying.
The extra metadata and safety accounting have a measurable cost; they do not
erase the parsing-only advantage on these two workloads.

`--benchmark` reruns both workloads with five alternating samples and records
compiler flags/version, host, implementation hashes, and retained array capacity.
Both implementations reuse parser/storage, but Tree-sitter returns/releases a
fresh tree each iteration. Timings exclude process startup, source I/O, and
serialization. They do not measure full compiler wall time or Tree-sitter peak
memory. Production performance must be measured separately with the scale and
language-comparison suites.

## First compiler consumer transition

`just test-compact-declarations` builds `build/dyn-compact-declarations`, an
opt-in compiler artifact using compact nodes for entry-declaration checks in
`src/frontend.c`. It identifies `main`, checks its location/signature, and reports
duplicate entries through the same byte-span diagnostic policy as the existing
reader. No generic interface disguises the two representations.

Tree-sitter still validates every source first and remains responsible for syntax
errors, recovery, and its raw 1024-level depth guard. Strict analysis then parses
each original file partition separately, including a reflection prelude when
present. Source maps restore original byte locations. Combining partitions before
parsing could change the interpretation of optional aliases or types at file
boundaries, so this transition preserves those boundaries.

Compact syntax rejection or internal work/recursion capacity uses the existing
declaration reader for that partition. Allocation failure and external work
exhaustion/cancellation stop analysis immediately; they never trigger fallback
or a false missing-main diagnostic. The shared work budget is not reset. The
extra parse consumes additional work units and memory; this artifact is a
compatibility transition, not a speedup. Recovery requests keep the old reader.

`check-declarations.py` compares declaration diagnostics and source maps directly,
proves the integrated reader is reached with allocation injection (including
merged partitions), and checks terminal resource failures. It compares 99 CLI
cases in text and JSON modes, including malformed input and both sides of the
production depth boundary. `frontend-state-compact-test` and
`frontend-failure-compact-test` reuse the existing concurrency/reentrancy and
allocation-failure contracts with the new reader enabled. Normal and sanitized
consumer tests pass, and both compiler artifacts passed the standalone regression
suite on the development Linux host.

Rollback is selecting the normal `dyn`/`dyn-release` artifact; neither includes
this parser. No persisted format, compiler option, source cache, AST ownership,
or editor parser is changed. The next migration must address consumers that
retain syntax, rather than assuming this transient declaration scan removes trees.

## Retained source consumer transition

`just test-compact-sources` builds `build/dyn-compact-sources`. This opt-in artifact
retains immutable compact snapshots beside valid prepared source revisions and
uses their nodes for module import discovery/prefetch, exported declaration
indexing, native link directives, reflection detection, and entry-declaration
checks. Import consumers receive borrowed text and byte spans through a narrow
reader; malformed sources retain the existing Tree-sitter reader.

Copies and merged source partitions retain atomic snapshot references. Rewriting
invalidates the old revision before preparing a replacement. Frontend checks reuse
the exact original partition snapshots and adjust diagnostics by the partition's
source-map offset. Snapshot callbacks are borrowed during creation only; allocation
failure, cancellation and external work exhaustion terminate preparation. Internal
compact syntax/capacity rejection retains the Tree-sitter fallback.

`dyn-compact-sources` also collects lexical visibility intervals directly from
compact snapshots. Function parameters, block locals, loop bindings, and case
bindings retain the existing source spans and declaration-order visibility.
Expression/type subtrees are skipped. Recovery or unavailable snapshots still use
the established Tree-sitter collector. `check-scopes.py` compares sorted binding
intervals and lookup-prefix bounds against that collector across fixtures and
std/test sources, including grouped/variadic parameters, shadowing, type patterns,
and loop labels. Allocation failures and exhausted work budgets must free the
partial index. Normal and ASan/UBSan gates passed.

`check-sources.py` exercises default empty-import sources, differential import
text/spans, reflection, revision isolation, merged lifetime, every snapshot
allocation failure and work exhaustion. `--sanitize` enables ASan/UBSan. The
source variant also runs existing frontend concurrency/failure contracts and
text/JSON diagnostic parity. CI exercises frontend/compiler/editor/generic contracts
and a paired cold compiler smoke with provenance and no timing threshold:

```sh
python3 tools/compare-compilers.py --candidate build/dyn-compact-sources --lines 1000 --flat 10 --runs 1 --output build/compiler-paired-smoke
```

This still stores both parser representations. Tree-sitter remains mandatory for
syntax diagnostics, raw depth validation, recovery, canonical interface
serialization and editor syntax. This source artifact still uses the legacy AST
reader; the separate artifact below migrates AST construction. Module reference
validation and rewrite edit collection already have direct compact readers, while
rewritten text retains the existing Tree-sitter reparse.
The added snapshot costs memory and parsing work; performance promotion requires
paired project evidence. Selecting the normal artifact rolls this transition back.

## Direct AST transition

`just test-compact-ast` builds `build/dyn-compact-ast`, adding direct declaration,
type, expression and statement lowering to the retained-source artifact. It uses
concrete snapshot/node/partition references, shared literal decoding and layout
helpers, and the existing declaration phase order. Named array extents preserve
local shadowing, declaration order and global constant lookup. Lazy aliases and
generic bodies retain snapshots through AST ownership; they do not depend on a
live Tree-sitter node when the complete compact path is selected.

Every original partition, including reflection prelude text, must have a qualified
snapshot for complete declaration lowering. Missing snapshots preserve the legacy
declaration phases; independently qualified function bodies can still use compact
nodes. A narrow compatibility check retains the legacy path for comments in enum
members, qualified struct literal names and case ranges, where raw anonymous-child
behavior is observable in existing diagnostics or spans. Resource failures are
terminal, not compatibility fallbacks. Editor/recovery requests use the legacy AST
reader throughout. Tree-sitter syntax errors and raw depth validation still run
before either AST reader; this does not remove the production parser dependency.

`check-ast.py` compares semantic AST fields and exact diagnostics, including
invalid programs, rather than comparing allocation padding or parser trees. It
also exhausts allocation/work budgets in focused fixtures and proves lazy generic
and merged-alias use after releasing the original syntax trees and source snapshot
references. Generated comment variants qualify the explicit compatibility path.
The aggregate std/tests/DNA run compared 1,567 inputs: 1,559 complete compact
lowerings and eight explicit declaration fallbacks; 30 additional inputs used
parser fallback. The latest sanitizer fixture/std/tests gate, including merged
alias lifetime, compared 405 inputs. External DNA remains an optional corpus.

```sh
just test-compact-ast
CC=/usr/bin/clang python3 tools/parser-experiment/check-ast.py --sanitize --corpus std --corpus tests --corpus /path/to/dna
```

After final module rewrites and reference/interface checks, the AST artifact's CLI
preflights every enabled source before releasing any project tree. Only valid,
fully compact-compatible projects qualify. Exact validated root spans survive in
a revision certificate; merging retains snapshots and partition offsets, including
the reflection prelude, without retained Tree-sitter nodes. A direct compact AST
entry no longer needs a Tree-sitter declaration table. Original and rewritten
text still undergo mandatory Tree-sitter syntax/depth validation before release.
One incompatible partition retains every project tree, preserving cross-file
legacy lowering. Work-budget, syntax-cache, query, vet and editor paths keep their
existing lifetimes. A recovery request on a certified source explicitly rebuilds
its original partitions. Revision invalidation clears the certificate.

A separate owned codegen entry still releases merged trees after complete compact
analysis when the earlier project release does not apply. Const preparation keeps
its ownership contract. `batch-trees-ast-test` asserts all-or-nothing release,
reflection partitions, explicit recovery, budget/cache exclusions, shared-copy
survival and cancellation. Sanitizer AST tests compare certified lowering and
exact diagnostics against legacy readers and exhaust direct-entry allocation
failures. Lazy aliases/generics retain their snapshots after release. Peak RSS
improvement requires paired measurements; release timing alone does not prove it.

The artifact also passes native frontend concurrency/failure contracts, 99
text/JSON diagnostic comparisons and the complete standalone regression suite.
ASan/UBSan qualification exposed three existing legacy AST defects, now repaired
in both relevant paths: grouped generic parameters could exceed their allocation,
nested case arms could invalidate an arena pointer, and invalid assignment targets
could leave an uninitialized statement. Focused regression fixtures cover all
three. Sanitizer gates disable recovery so a diagnostic cannot count as success.

## Compact-first validation candidate

`just test-compact-first` builds the separate `build/dyn-compact-first` artifact.
`dyn-compact-ast` remains the rollback artifact with mandatory initial Tree-sitter
validation. The new candidate first parses an immutable compact snapshot. Successful
sources with a pinned conservative raw-depth certificate can skip the initial
Tree-sitter parse. Module reference checks and rewrite edit collection consume
those snapshots directly; rewritten text must acquire a fresh certificate.
Legacy readers explicitly reconstruct a Tree-sitter tree when needed. Any embedded
NUL byte also selects Tree-sitter validation: mutation testing exposed different
comment-scanner behavior, so that byte domain is not certified. String literals
containing raw `//` or `/*` also use Tree-sitter: its lexer may select a comment extra at
a string-fragment boundary, including after escapes. Syntax rejection, internal parser capacity and uncertain depth retain that fallback.
Allocation failure and cancellation are terminal. Budget and syntax-cache entry
paths retain the existing Tree-sitter policy. No production default changes.

The pinned grammar inlines `expression`, `literal` and `statement`; `primary` is
the only removed nonterminal and cannot contain another `primary` directly.
Other removed children are terminal tokens, comments or string/character escape
leaves. Assign root depth zero and each compact child edge weight one plus its
primary flag. The maximum weighted depth plus one bounds visible raw Tree-sitter
depth; synthetic slice endpoints only overestimate it. A bound above 1024 triggers
Tree-sitter validation rather than rejecting the source. The 256-call compact
parser cap remains an independent reason to fall back. `grammar-pin.py` pins the
grammar, generated parser and scanner; changing them requires another audit.

This argument is conditional on normalized-tree parity. It does **not** formally
prove acceptance equivalence between parsers. `check-depth.py` audits the bound
against raw Tree-sitter depth for fixtures, corpus sources and long binary/field,
group and pointer chains around policy boundaries. `check-first.py` proves no-tree
preparation, explicit fallback, every snapshot allocation failure, cancellation,
revision invalidation and reused-source depth-error reset. `check-acceptance.py`
compares exact compiler exit status, stdout and diagnostics in text/JSON modes for
original fixtures and deterministic byte/token mutations, recording compiler/SDK
hashes and repro artifacts. Corpus agreement remains evidence limited to those
gates, not universal equivalence.

Mutation testing found two distinct NUL issues. Compact comment scanning accepted
a source rejected by Tree-sitter; excluding embedded NULs from certification fixes
that acceptance difference. A later diagnostic-range difference exposed an
existing heap overread: merged/rewrite original-text copies used `strdup` while
retaining a byte length extending beyond an embedded NUL. Both copies now preserve
exact bytes plus the final terminator. ASan reproduced the original overread, and
regressions cover default/source mapping, rewrite originals and both exact mutated
sources. The old allocator-dependent diagnostic endpoints are not an oracle.

```sh
just test-compact-first
CC=/usr/bin/clang python3 tools/parser-experiment/check-depth.py --sanitize --corpus std --corpus tests --corpus /path/to/dna
python3 tools/parser-experiment/check-acceptance.py --compiler build/dyn-compact-first --samples 10000 --corpus std --corpus tests --corpus /path/to/dna --output build/compact-first-new-evidence
```

## Remaining production gates

1. Finish qualifying retained syntax consumers, including canonical interface
   serialization. Opt-in AST, scopes, reference validation and rewrite collection
   already have direct readers; default artifacts retain the existing readers.
2. Extend compact-first acceptance evidence before changing defaults. Its pinned
   depth bound and Tree-sitter error fallback are qualified transition policies;
   independent diagnostic/recovery parity is not implemented. Preserve original locations, malformed and
   incomplete input policy, cooperative cancellation and allocation failures.
3. Remove strict-path tree ownership only after all retained consumers and explicit
   compatibility fallbacks can operate without it. Keep editor recovery and
   incremental parsing intact; avoid a generic facade that hides two parsers.
4. Compare cold project check/debug/release time and peak memory before changing
   defaults. Dual representations still incur extra parsing and retained memory;
   parser microbenchmarks alone cannot justify promotion.

The separate `tools/backend-experiment` consumes checked `DynIrProgram` and emits
an explicitly bounded scalar ELF subset. Neither experiment changes a production
parser/backend default or authorizes removing runtime checks.

The source candidate also selects module rewrite edits from compact nodes. Its
stackless walker preserves lexical shadowing and the existing replacement rules.
Incremental Tree-sitter edits still receive coordinates in the current generated
text, while diagnostic spans continue to map to the original source. Declaration
indexing, import aliases, and dependency ABI hashing also consume the retained
snapshot. Recovery and unsupported parser depth keep the existing readers.
`check-rewrite.py` compares normalized edit ranges, replacement text, byte columns,
declaration sets, and ABI hashes against the Tree-sitter readers. Focused fixtures
exercise every allocation failure and every work-budget cutoff, including sources
whose original diagnostic coordinates differ from the current text.

Serialized module interfaces now have a compact consumer as well. It computes
private-constant reachability through exported array extents across files, retains
canonical function signatures and global declarations, and produces the same
payload and hashes as the established reader. Mixed compact/recovery inputs keep
their source-owned lifetimes. A narrow fallback preserves the legacy serialized
payload for comments preceding a public global's bare type; it does not silently
reinterpret that existing interface format. `check-interfaces.py` compares exact
status, payload, source hash, and interface hash, including cross-file constant
cycles and mixed readers. It exhausts allocation failures and work budgets in the
compact constant/declaration helpers. Normal and sanitizer gates are included in
`test-compact-sources` and CI.

Immutable snapshots shrink their node allocation to the final count before
publication. This removes parser growth slack without changing node indices,
source bytes, or reference-count ownership. Snapshot allocation-failure,
cancellation, and concurrent lifetime tests cover the additional allocation.
