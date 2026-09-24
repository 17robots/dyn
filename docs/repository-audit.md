# Repository audit — original findings (2026-09-20)

**Update 2026-09-21:** The original 20 defects are fixed, with additional fixes,
regression gates and cleanup. See the [resolution report](audit/resolution-2026-09-21.md)
and [validation record](audit/fix-progress.md). The text below preserves the original
audit and its then-current observations; it is not the current remaining-work list.

Date: 2026-09-20. Scope: C compiler, runtime, LSP, grammar/editor integration,
Dyn std/vendor, examples, tests, build, and documentation.

**Result: 20 reproduced defects, plus a separate hardening and cleanup backlog.**
Existing regression suites pass despite these defects. This is a broad,
risk-directed audit, not proof that every line or possible behavior is correct.
Production sources were not changed. New files contain this report, reproducible
probes, and a mechanical SDK inventory.

## Evidence and coverage

- Inventoried 37 compiler C/header files (20,615 lines), eight runtime C/assembly
  files (1,915 lines), 91 std files (10,269 lines), and 13 vendor files (913 lines).
- [SDK inventory](audit/sdk-inventory.tsv) lists every std/vendor source file,
  its public declaration count, and direct Dyn test importers. Import presence is
  **not** proof of behavioral coverage; platform variants share module importers.
- Inspected compiler import validation/rewriting, semantic scope lookup, AST
  syntax handling, LSP document/completion/transport paths, runtime trace/unwind
  limits, and SDK parsing, ownership, capacity, and streaming contracts.
- Ran `just test-c`: passed, including 48 LSP contracts and checks of 123
  project/SDK files through the LSP.
- Ran `just test-libraries`: all 24 SDK fixtures passed in debug/release; 69
  codec reference cases passed in both modes.
- Ran `./projects/validate.sh`: 110 SDK/project modules checked, zero failures;
  project validation passed, including SQLite and SDL audio. GPU unavailable.
- Ran Clang static analysis on all 26 compiler C translation units. Three
  warnings remain for triage, discussed below; no analyzer compilation failures
  after adding `/usr/include` for this host's separately installed Clang.
- Compared compiler and local Zed grammar.js, parser.c, scanner.c, grammar.json,
  and node-types.json: all five pairs identical.
- No new sanitizer run, native Windows/macOS execution, GPU execution, network
  interoperability campaign, or performance benchmark was performed in this pass.
  Existing CI configuration and old reports are not evidence of a new run.

Current logs are under `build/repository-audit/`: `test-c.log`,
`test-libraries.log`, `projects.log`, `static-analysis.log`,
`repro-results.json`, `repro-summary.log`, and `editor-summary.log`.

Run from repository root:

```sh
python3 docs/audit/reproduce.py
python3 docs/audit/reproduce-editor.py
```

The first command generates 19 suspect-case programs and six positive controls,
then builds/runs each in debug/release. It reports failures without acting as a
CI gate. Most SDK failures are assertion panics; qualified-comment cases fail
compilation. The runtime trace probe deliberately panics and checks for the
surviving `main` frame in debug mode. Release correctly omits traces. All six
controls pass. The slot-map case records a lifetime-policy problem separately
from the 20 defects below. The second command reproduces module-scope and LSP
failures, with root-module and ordinary-directory controls.

## Reproduced defects

P1 = fix before relying on the affected behavior. P2 = correctness/compatibility
fix in the next cleanup pass. IDs group a shared root cause rather than counting
every failing input separately. SDK cases below fail in debug and release;
B05 is specifically a debug trace defect.

| ID | Priority | Location | Reproducer and observed failure | Fix / acceptance check |
| --- | --- | --- | --- | --- |
| B01 | P1 | `compiler/src/module.c:470`, `module_rewrite.c:221` | `comment-import-member`, `comment-import-type`: `bytes./* comment */equal` and `mem./* comment */Arena` treat the comment as the imported member. | Use the shared extra-skipping syntax accessors in both validation and rewriting. Test comments around every qualified operand, type, struct literal, and call in CLI and LSP. |
| B02 | P1 | `compiler/src/module_rewrite.c:331` | `scope-collision`: a parameter named `answer` alongside a module function named `answer` checks successfully in the root but produces `unknown name` when imported. | Resolve lexical bindings before qualifying identifiers. Make root/imported behavior agree; do not require users to rename otherwise accepted parameters. |
| B03 | P1 | `compiler/src/lsp_server.c:349`, `lsp_internal.h` | Open 33 documents with unsaved errors: only 32 receive diagnostics; document 33 returns null symbols with no explanation. | Grow document storage with explicit failure handling. Keep the bounded analysis cache separate from the set of open editor documents; test 33+ overlays and close/reopen. |
| B04 | P2 | `compiler/src/lsp_completion.c:192` | A directory named `bad"quote` with an exported completion causes an internal `response exceeds server capacity` error. Renaming the directory to `safe` restores completion. | Escape filesystem-derived JSON and Dyn string text through shared writers; generate a valid explicit alias or omit an unrepresentable import. Preserve other completions. |
| B05 | P2 | `compiler/runtime/linux_x86_64_start.S:131`, `reference_support.c:123` | `runtime-deep-trace`: recurse 70 levels, return, then panic in main. Trace is empty. Depth-10 control retains main. | Track logical depth/overflow separately from stored frames so dropped pushes do not pop retained frames. Check the analogous AArch64 implementation too. |
| B06 | P1 | `compiler/std/fs/fs.dyn:195` | `fs-self-copy`: copying a file onto itself truncates it to zero bytes and reports success. | Open without truncation, compare source/destination file identity, then truncate only after rejecting same-file copies. Include hard-link aliases and scratch-validation failures. |
| B07 | P1 | `compiler/std/fs/fs.dyn:25` | `fs-nul-path`: `write_all(".../nul-fixture\0ignored", ...)` succeeds against the shortened path. | Reuse checked C-string conversion and reject embedded NUL before any syscall. Review the duplicated macOS/Windows path helpers too. |
| B08 | P2 | `compiler/std/fs/fs.dyn:145,234` | `fs-read-proc`: `read_all("/proc/version")` fails although ordinary reads work. `metadata` determines size by seeking; read_all depends on that size and reopens the path. | Open once and read to EOF with an explicit maximum. A seek-based size is not general metadata; use descriptor metadata as a hint where useful. Cover nonseekable inputs and growing/shrinking files. |
| B09 | P1 | `compiler/std/crypto/kdf/kdf.dyn:23` | `hkdf-long-prk`: a 33-byte PRK disagrees with an independent Python HMAC reference because expand slices the key to 32 bytes. | Pass the complete PRK. Test 32, 33, 64, and longer keys, not only extract-generated 32-byte keys. |
| B10 | P2 | `compiler/std/crypto/pem/pem.dyn:30,49` | `pem-final-line`: matching END boundary at EOF is rejected; adding a newline succeeds. | Track whether the boundary was found independently of its byte offset. Cover LF/CRLF and final-boundary-at-EOF cases. |
| B11 | P1 | `compiler/std/net/http/http.dyn:175` | `http-invalid-transfer`: `Transfer-Encoding: chunkedjunk` is classified as chunked because matching accepts a prefix. | Parse complete case-insensitive coding tokens and framing rules. Test lists, unsupported codings, duplicate headers, and Content-Length interaction. |
| B12 | P1 | `compiler/std/net/http/http.dyn:652` | `http-close-body`: a 200 response with `Connection: close`, no Content-Length, and body `body` succeeds with an empty body. | Represent framing explicitly: fixed length, chunked, close-delimited, and no body. Respect request method/status. Also finish chunked responses at the terminal chunk rather than waiting for connection EOF. |
| B13 | P2 | `compiler/std/archive/tar/tar.dyn:45,103` | `tar-checksum`: changing a valid header name without updating its checksum is accepted. The unmodified-header control passes. | Share validated header parsing between buffered and stream readers, including checksum handling and explicit unsupported-format outcomes. |
| B14 | P2 | `compiler/std/archive/zip/zip.dyn:92` | `zip-empty`: the standard 22-byte empty ZIP end record returns Syntax instead of End. | Recognize/validate end records in both readers; cover empty, truncated, local-entry, and central-directory transitions. |
| B15 | P2 | `compiler/std/archive/zip/zip.dyn:58` | `zip-repeat-end`: calling next_stream again after End returns error=None and ok=false. | Make terminal End sticky and distinct from failure across repeated calls. |
| B16 | P2 | `compiler/std/image/png/png.dyn:100` | `png-adler`: decoder accepts a bad zlib Adler-32 checksum when the enclosing PNG chunk CRC is recomputed correctly. | Validate the zlib trailer after inflation; keep chunk CRC and decompressed-data checksum checks distinct. |
| B17 | P2 | `compiler/std/encoding/xml/xml.dyn:169` | `xml-invalid-attribute`: `xml.valid("<a broken/>")` returns true despite an attribute with no value. | Validate attributes and expose malformed attribute status separately from end-of-attributes. Define supported XML subset; test names, duplicates, entities, and forbidden characters. |
| B18 | P2 | `compiler/std/encoding/csv/csv.dyn:26` | `csv-trailing-empty-stream`: streaming `a,` yields `a` but omits the final empty field. Buffered scanning preserves it. | Track a pending field after comma and share scanner semantics. Differential tests across every input split and EOF position. |
| B19 | P2 | `compiler/std/net/url/url.dyn:17` | `url-relative-colon`: `path/to:file` becomes scheme=`path/to`, path=`file`. | Recognize schemes only in the initial segment and validate scheme characters before splitting query/fragment. |
| B20 | P2 | `compiler/std/path/path.dyn:84` | `path-dot-root`: `safe_join(buffer, ".", "file")` fails; an absolute-root control succeeds. | Compare normalized path components, treating current-directory roots explicitly. Retain lexical-only wording; this operation cannot enforce filesystem containment through symlinks. |

Standards checks used for the relevant expectations:

- HKDF expand accepts a PRK at least HashLen bytes and uses that key in HMAC:
  [RFC 5869 §2.3](https://www.rfc-editor.org/rfc/rfc5869.html#section-2.3).
- The standard PEM textual grammar permits omission of the final newline:
  [RFC 7468 §3](https://www.rfc-editor.org/rfc/rfc7468.html#section-3).
- HTTP framing requires distinguishing close-delimited and other message bodies:
  [RFC 9112 §6.3](https://www.rfc-editor.org/rfc/rfc9112.html#section-6.3).
- A colon is allowed in a later relative-path segment:
  [RFC 3986 §3.3](https://www.rfc-editor.org/rfc/rfc3986.html#section-3.3).
- PNG compression uses a zlib datastream including its checksum:
  [PNG compression](https://www.w3.org/TR/png-3/#10Compression).
- XML attributes require names and assigned quoted values:
  [XML start-tag grammar](https://www.w3.org/TR/xml/#NT-STag).

## Hardening and behavior that needs a decision

These are source-review findings or reproduced behaviors without an established
contract, not additional claims of independently reproduced defects.

1. **Slot-map lifetime policy.** `slot-map-reinit` proves that reinitializing the
   same backing and reinserting revives an old handle. `init` preserves nonzero
   generations. Define handles as belonging to one initialization and document
   that limit, or provide reset/epoch handling that rejects earlier handles.
   Define generation wrap behavior as well. Do not imply that generation alone
   identifies a map instance.
2. **HTTP worker lifecycle.** `std/net/http/concurrent` exits a worker after a
   single failed client request. Its comment assumes closing a shared listener
   stops blocked workers; that needs a real Linux shutdown test. `join` returns
   on the first worker error without joining later workers. Design explicit
   stop/wakeup and drain behavior, and preserve the number of successfully
   started workers on partial startup failure.
3. **DNS response validation.** `std/net/dns` uses fixed transaction ID 54849,
   does not reject the truncation flag, does not match the response question,
   and drops excess addresses without a capacity result. Define supported DNS
   behavior, validate compression references, and test hostile/truncated
   packets. Do not call this a demonstrated remote exploit.
4. **Archive completeness.** TAR exposes only the 100-byte name field and ignores
   the USTAR prefix. ZIP deliberately rejects data descriptors/encryption and
   does not provide full central-directory validation. Either support common
   variants or state precisely what the interfaces can read. Add entry-name,
   link/type, size, and extraction-policy tests before providing extraction.
5. **Streaming parser state.** XML requests one byte at a time and reparses the
   accumulated token. Gzip repeatedly inflates the accumulated prefix and stores
   the entire compressed and decompressed data. These are bounded adapters, not
   efficient incremental engines. Benchmark split input and long tokens, then
   keep parser state across reads. No timing claim was measured here.
6. **Uniform depth and capacity rules.** JSON pretty/stream encoders check depth;
   compact encoding does not. Regex parsing recurses for nested groups. Runtime
   unwind registration has 64 fixed slots and silently fails when exhausted.
   Add adversarial depth/thread/capacity tests and explicit outcomes rather than
   allowing accidental stack exhaustion or skipped cleanup.
7. **Handle initialization.** `fs.File{}` contains descriptor zero, while failed
   open returns -1. Document required constructors, or use an explicit valid
   state. Standardize same-slot close/destroy behavior across owned wrappers;
   copied native handles remain unsafe by convention.
8. **Ownership remains conventional.** Arena rewind/reset and native owner copies
   can invalidate references; the compiler has only narrow direct escape checks.
   Keep this limitation explicit. Do not expand self-hosting work before these
   reliability tasks and regression tests are addressed.

## Consolidation and removals

Apply the codebase-design skill's shared-implementation principle: consolidate
behavior where multiple callers need the same rule. Keep meaningful interfaces.

- **Compiler syntax:** finish routing positional access through `dyn_syntax`.
  Module validation and rewrite currently duplicate traversal assumptions.
  Longer term, resolve module-qualified names through bound identities rather
  than rewriting identifier spelling without scope information.
- **Protocol output:** centralize escaped JSON emission in LSP. Fixed response
  capacity, invalid JSON, allocation failure, and missing documents should have
  distinct outcomes; a quoted filename must not look like a capacity problem.
- **C-string paths:** remove private NUL-copy loops in fs/macOS/Windows in favor
  of one checked conversion. This consolidation directly addresses B07.
- **Bytes/text helpers:** replace duplicate byte equality/search implementations
  in flags, URL, XML, INI, and templates with `std/bytes` or `std/strings` where
  semantics match. Do not merge case-insensitive or protocol-specific rules by
  accident.
- **Templates:** text and HTML modules duplicate placeholder parsing, validation,
  retention, and lookup. Share that core; retain distinct HTML escaping/render
  behavior and document which HTML contexts are supported.
- **HTTP interfaces:** remove redundant stream-read/write aliases and trivial
  field-access wrappers when migration has no semantic cost. Share URL parsing
  with `std/net/url` while keeping HTTP-specific scheme/authority validation.
  Share decimal formatting rather than maintaining another implementation.
- **Error vocabulary:** `std/errors` currently has no std/vendor/project imports.
  Either implement real mappings at application seams or remove/defer the unused
  abstraction. Avoid forcing unrelated domain errors into one lossy enum.
- **Repeated directives:** collapse duplicate Linux `#target` directives in
  `std/sync`. Keep target-specific implementations in intentional files.
- **Thin crypto modules:** small forwarding modules can provide useful discovery
  and stable names. Do not delete them solely because they are short; remove
  duplicate implementations or unneeded aliases, not useful organization.
- **Arena policy:** keep fixed borrowed buffers, owned backing, and growing arena
  behavior in Dyn std. OS page allocation is the low-level mechanism supporting
  arenas; native provider handles have separate explicit ownership. This pass
  found no direct malloc/calloc/realloc calls in Dyn std/vendor source. That
  search does not mean native providers allocate nothing. C compiler allocation
  is a separate concern and does not need an arena-only rewrite.
- **Generated files:** retain generated parser/native binding artifacts needed
  for builds. Add reproducible generation/version checks instead of manually
  cleaning generated output or maintaining independent grammar edits.

## Grammar, tests, build, and documentation

- Add a dedicated Tree-sitter corpus for ambiguous imports, trailing-dot floats,
  comments between operands, malformed edits, and recovery. There is no
  `tree-sitter-dyn/test/corpus` directory; existing C/Python regressions remain
  valuable but do not replace grammar-level incremental parsing cases.
- Grammar currently accepts explicit enum values and local type aliases that
  the compiler deliberately diagnoses as unsupported. Decide whether these are
  reserved future syntax or should be removed. Keep one supported-feature table
  rather than treating grammar acceptance as implemented language support.
- Local Zed grammar copies currently match. `editor-grammar` refreshes them, but
  `test-editor` does not compare generated copies; the published extension uses
  a separately pinned repository revision. Add release-time provenance/drift
  checks. This audit did not verify the remote revision's contents.
- Extend Neovim tests to real completion acceptance/retriggering, nested imports,
  unsaved edits, quoted paths, and document-count growth. Keep the user's chosen
  behavior: completion inserts the package name without an automatic slash.
- Add table-driven and differential tests for parser families, not just round
  trips. Prioritize truncation at every byte, boundary capacities, empty final
  fields, corruption with otherwise valid framing, and terminal-state repeats.
- Fuzz valid typed/compiler programs in addition to token soup. Add import graph,
  comment-placement, and scope-preserving metamorphic cases; compare root versus
  imported execution and debug versus release.
- Add native ABI/layout probes for public SDL/Vulkan structs, callbacks, and
  provider handles, tied to declared supported header/provider versions.
  Existing SQLite/OpenSSL/zstd tests and provider CI are useful; they do not
  establish every native struct layout or GPU behavior.
- Benchmark before changing compiler allocation, cache indexing, or byte loops.
  Auto-import currently recursively scans and parses candidate modules per
  completion; a cached declaration inventory is a concrete candidate. Preserve
  invalidation for unsaved buffers, filesystem changes, target, and SDK location.
- Document/pin supported LLVM and Tree-sitter versions. Make currently links
  unversioned `-lLLVM` and relies on a separately installed grammar generator.
- Fix `docs/demo.md:16`, which still describes threads and filesystem paths as
  unsupported. Reconcile historical audit counts/log links with current status;
  several old referenced logs are absent in this checkout. Preserve history but
  do not present it as current validation evidence.
- Current std/vendor/projects check against the shipped SDK; no obsolete
  arena_init/arena_reset_to/arena_child or old sdk import paths were found in the
  searched Dyn sources. Private adapter functions named reader_read/writer_write
  are not obsolete public-call usage and should not be removed by name alone.

## Static-analysis triage

`static-analysis.log` reports:

- `analysis_cache.c:27`: hashing an allegedly uninitialized byte after successful
  stat. The code copies named fields into a uint64_t array rather than hashing
  struct padding; reproduce before changing behavior.
- `analysis_cache.c:240`: possible null eviction entry. Valid cache state requires
  a nonempty list whenever count is four; verify that invariant under failure
  injection before treating this as a reachable null dereference.
- `build.c:74`: allegedly uninitialized job fields. Jobs below count are populated
  before forking; analyzer loop modeling needs a concrete counterexample.

None is counted among the 20 defects. Do not suppress them merely to produce a
clean report, and do not report analyzer warnings as proven user-facing bugs.

## Suggested execution order

1. Fix B01–B04 with compiler/LSP regression cases: these directly affect ordinary
   editing, imports, and inconsistent diagnostics.
2. Fix filesystem data-loss/path handling, HKDF, and HTTP framing; add the new
   probes to the appropriate gating suites as normal positive assertions.
3. Fix remaining SDK parser/terminal-state and runtime trace defects, then
   strengthen streaming differential tests.
4. Consolidate syntax, path conversion, bytes, templates, and protocol writers
   behind the corrected shared behavior; migrate every shipped caller.
5. Resolve documented lifetime/format limits, add native/concurrency/fuzz coverage,
   and measure the identified performance candidates. Keep self-hosting deferred.
