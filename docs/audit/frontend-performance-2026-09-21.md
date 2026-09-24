# Compiler frontend and incremental performance — 2026-09-21

Implemented the four follow-up areas: source processing, AST construction,
incremental builds, and editor latency. This follows the dense constant-array
codegen optimization; the baseline already includes that earlier improvement.

## Changes

- Module rewrites edit and incrementally reparse their existing syntax trees.
  Native-link inspection shares source trees. Reflection discovery skips tree
  traversal when the source contains no `#typeof`; actual syntax still decides
  whether reflection is needed. Parse-error discovery skips error-free subtrees.
- AST wrapper handling avoids redundant child scans. Array literals use cursor
  traversal and reserve contiguous item slots before lowering nested expressions.
- Compiler executable hashing happens once per command and is inherited by build
  workers. Project fingerprints hash module groups directly instead of forking
  workers for short hashing tasks. Source grouping and key order are preserved.
- LSP updates retain precisely edited trees, including UTF-8 boundaries and
  transactional multi-change updates. Unchanged content can reuse semantic
  analysis across editor revisions. A project-owned MRU cache shares immutable
  raw dependency trees; every hit compares freshly read source bytes exactly.

The syntax cache holds at most 64 entries and 8 MiB of source text, **plus syntax
tree and entry overhead**. Oversized sources remain uncached. Optional cache
allocation failures fall back to normal parsing. Returned tree copies remain
valid after eviction or cache teardown.

## Measurements

Same host and benchmark workloads, run without concurrent tests/builds. Times
below are milliseconds. Raw samples, compiler hashes, phase details and RSS are
in [frontend-performance-2026-09-21.json](frontend-performance-2026-09-21.json).

| Workload | Before | After |
| --- | ---: | ---: |
| Unicode SDK check | 311.7 | 198.9 |
| Unicode SDK debug compilation | 345.0 | 229.8 |
| Unicode SDK release compilation | 377.0 | 262.7 |
| Unicode AST lowering, release | 44.2 | 17.5 |
| 1,000-function project check | 30.5 | 25.9 |
| 13-module cold build | 147.9 | 78.3 |
| 13-module unchanged build | 13.4 | 9.5 |
| 13-module private-body edit | 37.9 | 20.8 |
| 13-module public-interface edit | 117.7 | 77.4 |
| LSP real edit through diagnostics and symbol response | 10.46 | 7.88 |

Compiler phases use three samples, incremental builds seven samples except the
single cold build, and LSP edits twenty samples. Values are medians except that
cold sample. Small workload differences can be host noise: the 100-function
debug benchmark changed from 16.6 to 17.3 ms despite lower frontend phase times.
These results do not establish a speedup for every program. Peak compiler RSS
was broadly unchanged.

## Correctness checks

- Frontend state, allocation-failure, analysis-cache and codegen-failure tests,
  both normally and with AddressSanitizer/UndefinedBehaviorSanitizer.
- New syntax-cache tests: incremental versus fresh tree structure/positions,
  Unicode edits, malformed input, no-op edits, immutable copies, allocation
  failure fallback, entry/byte eviction limits and cache teardown.
- Fifty LSP contracts; 66 incremental/fresh editor comparisons; export changes
  with identical size/preserved mtime and no watcher notifications. These also
  passed under sanitizers.
- New debug/release incremental runtime tests verify unchanged/private/public
  changes and module reuse. Private-body edits preserve unaffected objects;
  public interface changes invalidate them. Passed under sanitizers too.
- Dense/sparse/imported/cached array regression tests, normally and sanitized.
- Compiler contracts and diagnostics, 192 metamorphic builds, two-million-loop
  stress test, 403,031 Unicode conformance vectors in debug/release, SDK library
  fixtures and project validation.
- Grammar/editor gates, module/build-plan/interface/binding checks, separate
  translation-unit build, and static analysis of 26 compiler files with no warnings.

## Limits and scope

Public-interface changes still conservatively invalidate all module objects.
Real LSP content edits still require semantic analysis; syntax caching does not
cache semantic state or skip fresh disk reads. The no-op semantic reuse path
still checks dependency state. There is no new stat-only build-cache shortcut.

SDK arena APIs and language semantics are unchanged. No new native platform tests
were added or run. Project validation reported the existing SDL GPU availability
skip in this environment.
