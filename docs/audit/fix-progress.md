# Audit validation record — 2026-09-21

Memory interfaces were subsequently [consolidated into std/mem](mem-consolidation-2026-09-21.md); the separate owner packages and take helpers described below are removed.

Follow-up: [lifetime, static-analysis and streaming changes](lifetime-followup-2026-09-21.md) supersede the corresponding remaining limits below.

Workspace implementation is complete. See the [resolution report](resolution-2026-09-21.md)
for fixes and supported-scope decisions, and [migration notes](../library-migrations.md)
for changed interfaces. Backup before edits: `/tmp/dyn-audit-fixes-before-14ppyifc`.

## Passed locally

- `make -j2 test-c`: compiler/runtime/frontend/allocation/module/editor contracts,
  including 48 existing LSP contracts and the new syntax-diagnostic/typed tests.
- `make sanitize-test-c`: ASan/UBSan frontend failure injection and full compiler
  suite, plus audit/compiler/LSP regressions. Sanitizers exposed the semantic
  table-relocation defects; their regressions pass after the fix.
- Separate sanitized SDK fixture builds (26 packages, debug/release), 192 typed
  metamorphic builds, final LSP/export-cache tests and cache-eviction test passed.
- `make test-libraries`: 26 SDK fixtures in debug/release, 69 reference codec
  cases, 15 compression cases at every input prefix, native/provider contracts,
  filesystem identity/capacity cases and audit regressions. The final audit gate
  has 28 programs in both modes, including PRKs of 32, 33, 64 and 100 bytes.
- Neovim menu selection/acceptance and manual-slash retriggering passed. Tests
  cover 65 shared overlays, close/reopen, unsaved export replacement and disk
  export edit/delete/recreate without watcher notifications.
- `make fuzz-c`: smoke corpus and 136 malformed/recovered versions compared
  across compiler check/build and incremental/full LSP analysis.
- `projects/validate.sh`: 109 SDK/project modules, zero failures; SQLite and SDL
  audio passed. GPU execution explicitly unavailable.
- `make per-file`, `make install-check`, `make test-grammar`, compile-cache
  benchmark (`7 --check`) and `tests/release-gate.sh` passed.
- Native ABI probes passed for SDL 3.4.16, Linux statx and Vulkan 1.4.357. Matching
  Vulkan headers were fetched separately; URL/hash are recorded in
  [header provenance](native-headers-2026-09-21.json).

## Measured / triaged

- Warm auto-import completion: 48.5 ms → 2.61 ms/request in the 200-module
  benchmark. Combined split-input gzip/XML workload: 7.26 ms → 1.11 ms.
  [Raw samples](performance-2026-09-21.json).
- Clang analyzed all compiler C translation units. Four warnings are retained
  with invariant/failure-injection triage in the resolution report; no claim that
  static analysis was warning-free.

## External release / execution limits

- `make verify-published-grammar` intentionally fails for the current stale Zed
  upstream pin. Local grammar, generated copies, corpus and hashes agree.
  Publish the reviewed grammar upstream and update the extension revision before
  releasing. No external repository or extension was published here.
- Cross-target builds pass, but native Windows/macOS execution and GPU behavior
  were not tested on this Linux host. Remote CI configuration was updated, not
  executed from this workspace.

Current logs live in `build/repository-audit/`: `fixes-test-c-final.log`,
`fixes-sanitize-final.log`, `sanitize-libraries.log`, `sanitize-typed.log`,
`sanitize-lsp-last.log`, `fixes-libraries-complete.log`, `audit-complete.log`,
`sanitize-audit-complete.log`, `projects-final.log`, `fuzz-final.log`,
`native-abi-complete.log`, `grammar-final.log`, `install-final.log`,
`static-analysis-final.log`, `compile-benchmark-final.tsv` and
`release-gate-final.log`. Logs are workspace artifacts, not permanent release
attachments. Original failing evidence remains alongside them.
