# Dyn 0.1 candidate notes

This is a development candidate, not a declaration that all targets/providers are
production-ready. See [readiness](readiness.md) for supported scope and outstanding
external evidence. Version remains `0.1.0-dev` until the release gate is signed off.

## Compatibility and fixes

- Pools/free lists round slot stride and arena backing alignment to at least
  pointer alignment. Small requested alignments no longer produce misaligned
  internal links. Caller-backed free lists must provide that effective alignment.
- Plain `std/c.char` follows default target signedness, including unsigned char
  on AArch64 Linux. Rebuild affected applications and regenerate bindings.
- Binding generation preserves string/comment boundaries, translates C escapes,
  retains nested pointer constness and emits valid void-returning callbacks.
  Non-prototype `()` declarations are omitted; use `(void)` explicitly.

- Excessive parser nesting now produces a diagnostic instead of overflowing the
  compiler/LSP C stack. The limit is 1024 syntax-tree levels, not 1024 characters
  or parentheses. Editor requests remain usable and a later valid edit recovers.
- C-compatible struct arguments/results now share target ABI lowering across
  direct/indirect calls and callbacks. Dyn-only foreign storage remains rejected.
  Rebuild all Dyn objects/libraries; frontend cache epoch is now 5. See [FFI](../ffi.md).
- Constant expressions handle numeric casts and forward constant dependencies;
  validation no longer incorrectly depends on the number of global declarations.
- Dyn caller defers run when a foreign function invokes a panicking Dyn callback.
- JSON nodes track their parent. Duplicate attachment, cycles and reparenting
  fail without mutation. `Value` layout changed; use `#sizeof`, never a fixed size.
- LSP analysis has cooperative cancellation and work/CPU budgets. Valid edits
  recover after cancellation/exhaustion; interrupted analyses are not cached.
- Binding generation offers JSON omission reports and C/Dyn layout verification.
  [Generated SDK reference](../reference/README.md) links contracts and fixtures.
- `--no-cache` no longer serializes module interfaces. Interfaces stay owned in
  memory; missing/unwritable cache storage falls back to compilation. Cached
  incremental builds still validate source/interface identity.
- Compiler unity builds now support nested `BUILD` directories.
- Generated C `long` bindings use `std/c` target aliases, including Windows LLP64.
  C octal integer literals are parsed correctly. Unsupported enum expressions are
  reported instead of crashing or inventing following enum values.
- Generic struct literals stay rejected. Completion items do not append `/`.
  Heap/buffer-backed arenas, growing arenas, scratch, pools and free lists remain
  together in `std/mem`; no ownership-transfer package is introduced.

## Release workflow and example fixes

- Component justfiles own compiler, project and grammar builds; the root forwards.
  Make entry points have been removed. Pass configuration as environment variables
  before `just`; native artifacts retain incremental rebuild checks.
- `just release-check` requires the full preview dependency set, runs the existing
  qualification suites and prepares versioned archives with source/archive hashes.
- Real Neovim checks cover completion, const/import diagnostic recovery and both
  semantic and Tree-sitter highlights after edits. Grammar generator package pins
  agree with the standalone generator pin.
- SDL GPU examples acquire a fresh command buffer every frame. Renderer examples
  redraw on expose/resize; the audio example flushes and waits for drain with a
  timeout instead of destroying a newly queued stream immediately.
- Native CI results identify the host and hashes of executed target probes.

## Release evidence

New gates cover deterministic uncached builds across worker counts, specification
fixture classifications, malformed input and editor recovery, C scalar/callback/
storage ABI, multi-worker synchronization, 64-document workspace churn, bounded
application/SDK soak, and unpacked SDK relocation. Provider probes record versions
and are compiled on each CI operating-system baseline. Scheduled sanitizer fuzzing
retains reproducible failure inputs and successful soak reports.

Packages include a content-hash manifest and archive checksum. Linux compiler
packages require the system shared libraries recorded in that manifest; LLVM,
Tree-sitter and cross-link tools are not bundled. Local LLVM 22 artifacts are not
the pinned LLVM 19 release artifact.

The published Zed grammar remains stale at its current immutable pin. A reviewed
source bundle is prepared separately; publication, pin refresh and installed
extension verification are still required. Cross-linked target probes need actual
native execution. GPU/hardware validation and independent security review are not
implied by local tests.


## Agent lookup and observable memory contracts

- `dyn docs MODULE --json` exports versioned syntax-only public declaration data,
  source contracts, locations, target gates and a freshness fingerprint. This is
  not a complete semantic program database or a lifetime analysis result.
- Slot-map handles now include backing identity; foreign-store handles are rejected.
  Rebuild consumers. `copy_into` retains bytes in caller storage with explicit
  missing/capacity results. Existing borrowed views still require lifetime discipline.
- Arena and slot-map snapshots expose current counters without allocation or borrowed
  pointers. The memory tour demonstrates handles, copy-out, snapshots and bounded
  profiling, and is included in workspace-built SDK archives.
- `just test-agent-readiness` verifies declaration queries and debug/release memory
  contracts. The application-writing guide describes enforced guarantees and limits;
  no general memory-safety or measured AI-success claim is added.

### Semantic inspection and isolated preview

- `dyn query` and `dyn-query` add a compiler-resolved JSON/SQLite project snapshot,
  with symbols, types, references, calls and documented contracts. Unknown effects
  and incomplete reference coverage remain explicit.
- Straight-line lifetime diagnostics cover aliases, direct aggregate fields and
  tracked arena-reset misuse. This remains an incomplete check, not a borrow checker.
- `std/observe` adds bounded caller-owned runtime logs; arenas expose peaks/failures.
  Rebuild Arena layout consumers. `slot_map.lookup` adds a tagged borrowed result.
- Linux filesystem capabilities enforce relative lookup via `openat2`; separate
  `dyn-sandbox` applies process isolation, syscall restrictions and resource limits.
  The loopback browser playground uses this runner and fails closed.
- A devcontainer builds the preview on Ubuntu 24.04. The LLVM baseline is now 19:
  clean-machine qualification found LLVM 18 lacks the debug-record APIs in use.
- Six fresh-context authoring trials produced 5/6 first-check passes and 6/6 final
  behavioral passes. Results and scope limits are in `benchmarks/ai/README.md`.

These features add no language syntax. Read `docs/preview-tools.md` for guarantees,
commands and limitations. Distribution terms remain a draft until adopted by the
copyright owner; local candidate preparation does not publish Dyn.
