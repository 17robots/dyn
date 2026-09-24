# Repository audit resolution — 2026-09-21

Memory interfaces were subsequently [consolidated into std/mem](mem-consolidation-2026-09-21.md); the separate owner packages and take helpers described below are removed.

Follow-up: [lifetime, static-analysis and streaming changes](lifetime-followup-2026-09-21.md) supersede the corresponding remaining limits below.

The 20 original reproduced defects are fixed. Regression coverage is now gating,
not just an audit script. Hardening, consolidation, project migration, grammar,
ABI, fuzz and performance work from the audit are implemented or have explicit
supported-scope decisions below. This is not a claim that every possible bug has
been found or that the language has complete memory-safety enforcement.

## Correctness changes

| Findings | Resolution and regression |
| --- | --- |
| B01–B02 imports/comments/scope | Module validation and rewriting share extra-skipping syntax and lexical-binding queries. Root/imported behavior is checked by `typed-metamorphic.py` and editor contracts. |
| B03 open documents | Dynamic document and analysis-input storage; 65 same-project overlays, growth and close/reopen tested. |
| B04 quoted auto-import paths | Shared JSON escaping handles all control bytes; completion omits paths the module loader cannot represent. Invalid JSON, response capacity, transformation and allocation failures have distinct messages. |
| B05 deep traces | Logical depth remains separate from the 64 retained frames on x86-64/AArch64 support paths. Returning from deep recursion preserves main. |
| B06–B08 filesystem | Checked C-string paths; compare open-file identity before copy truncation; statx metadata; one-open read-to-EOF with maximum/capacity rollback. Hard-link, empty-scratch, exact-fit and proc-file tests. |
| B09–B10 HKDF/PEM | HMAC receives the complete PRK; PEM tracks a found END boundary separately from EOF position. |
| B11–B12 HTTP | Exact transfer-coding parsing, explicit framing, no-body/method/interim handling, close-delimited reads, non-mutating incomplete chunk decoding and terminal-chunk completion. |
| B13–B15 archives | Shared TAR checksum/header validation and USTAR metadata; ZIP empty EOCD and sticky End. Truncation/metadata tests added. |
| B16 PNG | Verify decompressed zlib Adler-32 independently of PNG chunk CRC. |
| B17 XML | Attribute errors, duplicate/name/entity/character validation; retained stream scanning state. |
| B18 CSV | Streaming trailing-empty-field behavior matches buffered scanning. |
| B19–B20 URL/path | Validate schemes in the initial path segment; normalize current-directory safe_join roots. |

Additional defects reproduced during implementation:

- **B21:** HTTP worker startup interpreted positive thread IDs as failure.
  It now treats only negative spawn results as errors; a live TCP integration
  test covers malformed-request recovery and shutdown during a blocked read.
- **B22:** A separate 64-item diagnostic collector silently lost errors even
  after document storage grew. Diagnostics now grow, snapshots own copied
  collections, and allocation failure reports incomplete results explicitly.
- **B23:** Recursive semantic analysis kept pointers into tables that could
  reallocate. ASan reproduced freed pointer-type access during an indirect call
  and freed AST access during reflection in an array. Checking now retains
  stable indices/scalar signature data and reacquires table entries. The
  `sema-table-growth` fixture and HTTP audit cases cover the failures.
- **B24:** Calls, address-taking and reflection could choose a module function
  over a same-named parameter. Builtin operands parsed as type syntax could also
  be incorrectly qualified in imported modules. Binding precedence is now
  consistent, covered in root/imported debug/release metamorphic programs.
- **B25:** Interface preparation could reject malformed syntax without a useful
  build diagnostic. Failures now pass through the canonical frontend collector;
  build/check diagnostic tests enforce an error message and nonzero exit.

## Hardening and consolidation decisions

- Slot-map reinitialization advances generations; exhausted generations retire.
  Handles still belong to their backing instance by convention.
- Workers survive bad clients, stop blocked socket operations, attempt all joins,
  and drain partial startup. Arbitrary handler computation is not cancellable.
- DNS uses randomized IDs, matches the original question, validates compression,
  rejects truncation and reports address capacity. This remains an IPv4 UDP
  resolver, without DNSSEC or TCP fallback.
- TAR exposes prefix/link/type metadata. ZIP remains a local-entry reader, not a
  full central-directory validator. Supported variants and extraction limits are
  recorded in [library migrations](../library-migrations.md).
- XML scans retained token state and reads chunks. DEFLATE/gzip share resumable
  block/bit engines with the buffered APIs. Caller-owned complete working sets
  are still required; no hidden allocation or constant-memory claim was added.
- JSON compact encoding has a 256-depth bound; regex compilation has a 128-group
  depth result. Runtime unwind overflow panics explicitly; a deterministic
  65-registration test checks exhaustion and slot reuse.
- C-string path copying, matching byte helpers, template parsing/lookup and HTTP
  decimal formatting now use shared implementations. HTML escaping remains a
  distinct rendering policy. Removed redundant HTTP forwarding/accessor APIs,
  unused std/errors and duplicate sync target directives. Thin crypto discovery
  modules remain intentionally available.
- tar-inspect uses the checked std TAR reader and prints USTAR prefixes. It,
  json-check and recursive-search obtain heap backing through `std/mem/owned`.
  SDK/project callers use the current interfaces.
- File constructors and native ownership/reset rules are documented. Borrowed
  buffers can live on stack or in arenas. Arena and provider ownership remains
  conventional; no complete borrow checker or self-hosting expansion was added.
- Positional syntax handling is consolidated where module validation/rewrite
  share it. Module spelling qualification remains the source-composition seam;
  local resolution precedes qualification and semantic/IR references use IDs.
  A wholesale replacement of module composition is not required by these fixes.

## Grammar, build and editor checks

- Seven corpus cases cover import/global ambiguity, aliases, comments, trailing
  dots and malformed recovery. Generation is reproduced with CLI 0.25.8 and
  compared byte-for-byte; all five local Zed source/generated pairs are gated.
- `docs/language.md` distinguishes supported features from reserved local aliases
  and explicit enum discriminants. Grammar acceptance is not compiler support.
- Neovim tests actually select and accept menu entries, check inserted text, then
  type `/` and wait for nested packages. No slash is inserted by completion.
- `typed-metamorphic.py` checks 24 valid programs across root/imported, comment and
  debug/release transformations (192 builds). Existing malformed incremental/full
  editor fuzzing remains in place.
- SDL size/alignment/field-offset and C callback probes compare against installed
  headers. Linux statx offsets are checked. Vulkan loader layouts also passed against matching upstream 1.4.357
  headers fetched for this run; the probe reports a skip when headers are absent.
- Tree-sitter generator/runtime and LLVM CI selection are documented in
  [toolchain](../toolchain.md). Make accepts versioned llvm-config installations.
  Stale thread/filesystem demo wording is corrected. The mechanical
  [SDK inventory](sdk-inventory.tsv) is reproducible with `tools/sdk-inventory.py`.

## Measured performance

`benchmarks/lsp-autoimport.py` uses 200 workspace modules plus the SDK. Median
incremental completion cost fell from **48.5 ms to 2.61 ms** on this host, with
similar cold request cost (~55 ms). A bounded 512-entry/4 MiB declaration-name
cache checks file identity, size and nanosecond modification/change timestamps.
Open buffers bypass disk/cache; discovery still runs each request, preserving
add/remove/SDK/target behavior. Watch/config notifications clear retained entries.

`benchmarks/streaming.py` compares the saved pre-change SDK with current std under
one-byte input reads. Its combined gzip/XML workload fell from **7.26 ms to
1.11 ms** median. These are workload measurements, not universal speed guarantees;
raw samples are in [performance results](performance-2026-09-21.json).

## Static-analysis triage

The full Clang run reports four warnings; none was reproduced as a reachable
failure. They are retained as triaged findings, not silently suppressed:

- Stat hashing reads named integer fields only after successful stat; it does not
  hash structure padding. The analyzer treats a stat field as uninitialized.
- Analysis-cache eviction requires a nonempty list when count is four. Failure
  injection, repeated eviction and retained-snapshot tests verify ownership/count
  behavior. The analyzer loses that linked-list/count invariant.
- Build jobs below count are assigned before workers fork. Build-plan tests cover
  grouping, excess workers, out-of-order completion and interrupted waits. The
  analyzer loses the initialized-prefix relationship between the loops.
- LSP document count becomes positive only after successful table growth. The
  analyzer treats escaped count state as nonzero while retaining the initial
  null table. The 65-overlay and sanitizer tests exercise growth and lifetime.

## Validation and external limits

Local validation logs are under `build/repository-audit/`; these are workspace
artifacts rather than promised permanent links. The completion record is
`fix-progress.md`. Cross-linking is not native Windows/macOS execution, and
unavailable GPU/header checks are explicit skips.

The published Zed grammar revision is **stale**: grammar.js, parser.c,
grammar.json and node-types.json differ; scanner.c matches. The new
`make verify-published-grammar` release gate correctly fails on that pin. Local
fixes and provenance are ready; publishing the grammar and updating the extension
revision is an external release step, not performed by this workspace cleanup.
