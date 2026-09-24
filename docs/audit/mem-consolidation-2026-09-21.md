# Memory module consolidation

The public memory interfaces now live together in `std/mem`: fixed arenas,
growing arenas, scratch scopes, pools, free lists and byte operations.
This supersedes the `owned`/`growing` package and `take` recommendations in the
[lifetime follow-up](lifetime-followup-2026-09-21.md).

- Removed `std/mem/owned`, `std/mem/growing`, and both `take` functions.
- `mem.Arena` contains its buffer, cursor and heap-ownership flag. Heap-backed
  `arena_create` and borrowed `arena_from_buffer` use the same allocation interface.
  Callers keep the arena in place, pass its pointer and release it in that scope.
- `arena_release` frees heap backing, clears the same arena slot on success,
  preserves ownership on failure, and never frees caller-supplied buffers.
- `mem.GrowingArena` retains explicit growth, stable addresses, reset/reuse and
  release. Its blocks use the same fixed-arena implementation. It remains distinct
  from a contiguous `Arena`, so existing fixed-buffer SDK contracts stay intact.
- Pool and free-list interfaces are retained in `std/mem`, as requested.
- OS mapping operations moved into private target files beside `mem.dyn`.
  Public OS page-allocation/release wrappers were removed and callers migrated.
  Windows uses a link alias to its existing last-error entry point to avoid
  duplicate foreign-symbol declarations when importing both mem and os/windows.
- Projects, benchmarks, SDK fixtures, platform probes and reference tests use the
  consolidated interface. Neovim and LSP nested-import tests now use packages
  that still have subpackages, while retaining slash-insertion assertions.

See [memory contracts](../memory.md) and
[interface migrations](../library-migrations.md#memory-module-consolidation).
Workspace validation logs are under `build/mem-consolidation/`.

Validation: compiler/contracts suite, SDK/library suites, sanitizer compiler
suite and project validation pass. Neovim still accepts package names without inserting `/`. Windows PE and
macOS Mach-O arena/platform probes cross-link successfully. The range-optimization
gate now examines loop blocks, allowing required arena-setup checks outside loops;
vectorization and absence of per-iteration overflow guards remain required.

Native Windows/macOS execution is still separate from the cross-link checks.
Arenas remain ordinary std code; no compiler move/ownership feature was added.
