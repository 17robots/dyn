# Changelog

Upgrade notes for Dyn code and the agents that write it. Newest release first.
Previews 9 to 11 are backward compatible: code that built on preview 8 still
builds. The one tooling exception is `dyn fmt --check`, which applies stricter
layout rules from preview 9 on. The other migrations below are cleanups, not
required fixes.

## Upgrading

Pin the new version and its checksums from [`mise.example.toml`](mise.example.toml),
run `mise install`, and confirm with `dyn version`. Restart editor language
servers so they pick up the new `dyn`.

## 0.1.0-preview.18

- A mutable `*T` now converts to `rawptr` implicitly, like C's `void *`:
  `free(task)` replaces `free(#cast(rawptr) task)`. Existing casts still
  compile; delete them at your convenience. `rawptr` to `*T` and `*const T` to
  `rawptr` still require `#cast`.
- Faster `dyn check` and builds: modules are parsed in parallel and only once,
  builds analyze the program once instead of once per module, and large
  modules are compiled in parallel chunks. Debug builds emit less code for
  runtime checks.

## 0.1.0-preview.17

- Fix using `std/io` standard streams and `std/os/wasi` together: shared raw
  declarations prevent duplicate foreign symbols without changing public APIs.
- Fix debug builds where a hoisted stack slot retained another function's debug
  location and LLVM rejected the module.
- See the [migration guide](docs/migrations/0.1.0-preview.17.md) for standard
  stream replacements in older examples and explicit arena ownership transfer.

## 0.1.0-preview.16

This release changes allocation names and adds typed allocation. Follow the
[migration guide](docs/migrations/0.1.0-preview.16.md) before updating callers.

- Breaking local API cleanup: ordinary allocation builtins and arena operations
  return failure; `_or_panic` explicitly selects panic on failure. Existing callers,
  editor help, and examples are migrated. See [replacement table](docs/memory-api-direction.md).
- Add fallible pool/free-list construction, allocator-output strings and INI
  parsing. Growing allocator callbacks no longer zero payloads redundantly.
- Keep lifetime diagnostics narrow. No borrow checker, ownership annotations,
  automatic reclamation, or implicit allocator is introduced.

- Add experimental primitive `Allocator`, fixed-callback construction, typed
  allocation builtins and `#AllocResult` with named `AllocError` categories.
  Fixed/growing arena adapters, reflection, editor support, failure tests, and
  [design documentation](docs/allocator-design.md) accompany the feature.

`std/mem` adds binary byte units `KiB`, `MiB`, and `GiB`, plus
`size_for(count, element_size)`. Check the returned `ok` before using `bytes`:
overflow returns failure instead of trapping, and zero count or element size
succeeds with zero bytes. The result describes payload only, excluding alignment
padding and container metadata. Allocation naming changes are listed below.

Fixed-array types now accept integer constants and simple nonnegative constant
arithmetic, such as `[4 * mem.KiB]u8`, including imported constants. Runtime-sized
stack arrays remain unsupported. Constants needed by exported layouts and public constants are preserved
transitively in module interfaces, including dependencies from other files.
Unrelated private constants remain excluded.

`arena_push_array` checks count multiplication and performs zeroed aligned
allocation while retaining explicit element size, alignment, and pointer casts.
`arena_take` transfers a fixed-arena descriptor and clears the old slot. Direct
copies of known arena descriptors warn; use `--warnings-as-errors` for a hard gate
or `--no-warnings` to suppress these warnings. Existing reset diagnostics now also
recognize literal `arena_rewind(..., 0)`. These are narrow checks, not borrow checking.

Growth remains explicit. `growing_create_bounded` limits total requested backing
bytes, `growing_snapshot` reports retained storage, and `growing_trim` releases
empty blocks without invalidating live allocations. Reset still retains blocks.
Trim and release preserve remaining ownership after partial failure.

`dyn docs --json` adds `contracts` summaries sourced from labelled adjacent comments.
The schema remains version 1 with additive fields; full comments remain available.
The new [memory guide](docs/memory-patterns.md) is exercised in debug and release
by `tests/documentation-examples.py`.

## 0.1.0-preview.15

`std/testing` imports work on macOS and Windows again: Linux-only temporary
directory and path helpers are isolated behind their target guard.

Release debug information now permits inlining. New opt-in `--cpu native`,
`--opt-level 3`, `--opt-remarks` and x86_64 Linux ThinLTO `--sample-profile`
controls support measured tuning; portable O2 remains the default. CPU features
and profile contents participate in cache identity.

The standard library adds prepared allocation-free linear-time byte search,
string-map reservation/clear and caller-owned sample statistics. Byte search
filters mismatching tails, large buffered writes avoid staging copies, and byte
builders extend the last arena buffer in place when possible. Existing storage,
overlap and failure contracts remain covered by regression tests.

`tools/performance-suite.py` records isolated cold, unchanged, novel-edit and
runtime samples with executable size and per-child memory measurements. See the
README for tuning, profiling and ownership contracts.

## 0.1.0-preview.13

### Reuse release-link optimization

On x86_64 Linux with LLD, release builds now emit real ThinLTO summaries and
module hashes. Previously, plain bitcode silently selected full LTO and repeated
whole-program optimization whenever linking ran. Native backend results now use
a periodically pruned cache; `--no-cache` bypasses it and `--jobs` limits backend
workers as well as frontend workers.

In a local LLVM 23 comparison on DNA, a cached relink fell from 4.50 seconds to
0.52 seconds. Cold builds and root-module edits still took about 6.4 seconds;
this change does not claim the same speedup for those workloads. Cache reuse and
dependency invalidation were also checked with LLVM/LLD 19.

Building the compiler from source now needs a C++ compiler and LLVM development
headers for the small ThinLTO writer. Packaged SDK users need no additional tools.

## 0.1.0-preview.12

### Compiler correctness and scaling

Bounds and overflow proofs now discard facts invalidated by branches, calls,
indirect writes, or loop-carried assignments, and respect the target pointer
width. Compound assignment evaluates its destination once. Floating-point
inequality handles NaN correctly. Forward global initializers and dependent
struct/enum layouts resolve in dependency order, and type-capacity overflow
reports an error instead of corrupting interned types.

Function/global lookup, module declaration lookup, source locations, and guard
propagation avoid repeated whole-program scans. Range-analysis scratch is scoped
to each function. String constants use bulk LLVM construction. Cache accounting
includes retained frontend storage and estimated syntax-tree storage; executable
cache keys include the selected runtime objects. LSP semantic tokens avoid
repeated expression scans and repeated UTF-16 prefix conversion.

### Reliable native deferred cleanup

Windows and macOS unwind state is isolated by thread. Panic unwinding restores
Windows XMM6–XMM15 and floating-point controls, and AArch64 d8–d15, so deferred
cleanup retains its floating-point values. Context sizes follow the target ABI;
Linux x64 keeps its existing 128-byte context.

### Standard library performance and fixes

Compiled regex matching uses an iterative machine with workspace independent of
input length. Streaming deflate uses circular history. String-map deletion closes
probe gaps, slot-map insertion skips the occupied prefix, and arena-backed pools
use optional occupancy bits for constant-time release. HTTP readers scan fragmented
headers and chunk framing incrementally. JSON output escapes control bytes, JSON
string decoding releases unused arena space, and decimal formatting avoids
rounding large integral doubles incorrectly.

**Regex migration.** `regex.Match` now includes `error: MatchError`, with `None`
and `Capacity` variants. Check `error` before treating `ok == false` as no match.
`find_compiled` uses 4096 `usize` workspace slots; larger programs should allocate
`match_workspace_size(program, capture_count)` slots and call
`find_compiled_workspace(program, text, captures, workspace)`. This API performs
no hidden allocation and clears captures on failure.

**Allocator and container layout.** `mem.FreeList` gains `occupied: []u8`, and
`slot_map.SlotMap` gains `next_free: usize`. Use their initializer functions rather
than depending on struct layout. Pool occupancy storage is optional: caller-buffer
and exact-capacity arena initialization retain their existing usable capacity and
linear validation fallback. Rebuild consumers that depend on these layouts.

The regression suite now covers allocation failures, compiler miscompilations,
cache retention, fragmented HTTP, regex capacity, pool ownership, deflate history,
and native unwind register preservation. Local Linux checks and cross-target ABI
harnesses pass; the release workflow separately requires native platform checks
and validated SDK packages before publication.

### Faster, private `memcpy`, `memmove` and `memset`

The runtime's `memcpy`, `memmove` and `memset` copied one byte at a time and
were exported from every executable. A program that also linked a C library and
shared libraries (SDL, FreeType, GPU drivers) replaced the C library's versions
for all of them. They now move eight bytes at a time, use `rep movsb`/`rep
stosb` for blocks of 512 bytes or more on x86-64, and have hidden visibility,
so each shared library keeps its C library's versions. No code changes are
needed. Projects that hid these symbols with a linker version script can keep
it; it is no longer required.

### Process exit runs C exit handlers

A program that links the C library now ends through its `exit`, so `atexit`
handlers run and buffered `printf`/`puts` output is flushed. Before, the
runtime exited with a raw syscall and output written to a pipe or file was
lost. Programs without the C library exit with `exit_group`, which also ends
other threads. `os.exit_process` in `std/os/linux` uses `exit_group` too; it
used to end only the calling thread.

### Dyn functions may share a name with an extern's C symbol

A Dyn function named like the C symbol of an extern in another file of the
same module, such as `pub fn free` next to `extern fn libc_free "free"`, failed
to link with an undefined `free.1`. The Dyn function now gets a private symbol
and both resolve.

### Global shadowing is checked in imported modules

A parameter named like a global was rejected in the root module but accepted
in imported modules. Both now report one error, "parameter has the name of a
global; shadowing is forbidden", without a follow-on "unknown name" for each
use. Rename the parameter if an imported module stops building.

### Numeric literals adopt the other operand's type on either side

A literal on the left of an operator defaulted to `i32`, so `8 + step` with
`step: u32` failed with mismatched types while `step + 8` built. The literal
now takes the other operand's type on either side, for arithmetic, bitwise and
comparison operators. Casts written to work around this can be removed.

### Hex literals containing `e` or `E` are integers

`0x1E1E2E`, `0xE` and any other hex literal with an `e` or `E` digit were read as
floating-point numbers, so `x: u32 = 0x1E` failed with "expected u32, found
f32". They are now integers like every other hex literal.

## 0.1.0-preview.11

### `#reverse` for-in loops

`#reverse` walks a range, array, or slice from its last value to its first:

```dyn
for i in #reverse(0..count) {   // count - 1, ..., 1, 0
  _ = values[i]
}
for i in #reverse(1..=count) {  // count, ..., 2, 1
  _ = i
}
for value in #reverse(values) { // last element first
  _ = value
}
for *item in #reverse(values) { // mutate from the end
  item.* += 1
}
```

- `#reverse` visits exactly the values of the forward loop, in the opposite
  order. `#reverse(0..0)` and `#reverse(5..2)` run no iterations.
- Unsigned bounds never wrap: `#reverse(0..=n)` stops after `0`.
- `#reverse` is valid only as a `for` iterable. `reverse` remains an ordinary
  name.
- A descending range such as `5..2` still runs no iterations. Use `#reverse`
  to count down.

**Migration.** Replace manual down-counters:

```dyn
i := count
for i > 0 {
  i -= 1
  work(i)
}
```

with `for i in #reverse(0..count) { work(i) }`. Convert only when `i -= 1` is
the first statement of the body, the body never assigns `i` or takes `&i`, and
`i` is not used after the loop. `continue` is safe here, because the manual loop
already decremented before it.

### Editor completion

Completion details for declarations with quoted text, such as
`extern fn poll "SDL_PollEvent"(...)`, no longer show doubled escapes.
`#reverse` appears in completion and has hover documentation.

## 0.1.0-preview.10

### Range for-in loops

`for` accepts an integer range after `in`:

```dyn
for i in 0..count {    // 0, 1, ..., count - 1
  _ = values[i]
}
for i in 1..=count {   // 1, 2, ..., count
  _ = i
}
```

- Both bounds share one integer type. A literal bound adapts to the other bound,
  so `0..count` has `count`'s type and `0..#len(values)` is `usize`.
- When both bounds are literals, the binding is `usize`, or `isize` if a bound
  is negative. `for i in 0..3 { values[i] }` indexes directly.
- Bounds evaluate once, first bound first. `5..2` runs no iterations.
- The binding is a copy. Assigning it inside the body does not change the
  iteration. `for *i in 0..n` is an error.
- `..=` may end at the type's maximum. `for b in 250..=top` with `top: u8 = 255`
  runs 6 times without overflow.
- Mixed bound types such as `u8..u32` are an error: "range bounds require the
  same integer type".

**Migration.** Replace manual counter loops:

```dyn
i: usize = 0
for i < count {
  work(i)
  i += 1
}
```

with:

```dyn
for i in 0..count {
  work(i)
}
```

Convert only when all of these hold, or behavior can change:

1. `i += 1` is the last statement of the body.
2. The body never assigns `i` or takes `&i`.
3. The body has no `continue`. In a manual loop `continue` skips the
   increment; in a range loop it advances to the next value.
4. `i` is not used after the loop. A range binding exists only inside the loop.
5. The body cannot change the end bound. The manual loop rereads `count` on
   every iteration; the range reads it once. Keep manual loops whose end is a
   field reached through a pointer, a global, or a local whose address is taken.

Loops that step by more than one, count down, or change the counter inside the
body stay as condition loops.

### Names are reusable after their scope ends

A local declared in a block or loop no longer reserves its name for the rest of
the function. Consecutive loops can each use `i` or `value`, and a name can be
declared again after an earlier block ends:

```dyn
for value in first {
  _ = value
}
for value in second {
  _ = value
}
```

Shadowing is still forbidden: a local cannot reuse the name of a visible local
or parameter, including an enclosing loop's binding.

**Migration.** Names such as `i2`, `index_b`, or `value_2` that only avoided the
old rule can go back to the natural name. Previously, redeclaring a name after
its block also reported a spurious `unknown name` at the redeclaration; that is
gone.

### Standard library

122 std counter loops now use range loops. No public API changed.

## 0.1.0-preview.9

### `dyn fmt` works on real modules and enforces layout

`dyn fmt DIR` used to run full semantic checks without loading imports, so any
module with `use` failed with "unknown name" errors. It now only requires every
file to parse, validates all files before writing any, and reports the first
syntax error per file.

`dyn fmt` and editor formatting now apply:

- One statement per line. `if ready { return }` becomes three lines, and
  `x := 1 y := 2` is split.
- One space after every comma: `add(4, 2)`, `[1, 2, 3]`. No space is added
  before a closing bracket or at a line end.
- LF line endings, no trailing spaces or tabs, and a final newline.

The formatter only inserts or removes whitespace between tokens, so it cannot
change behavior. Running it twice changes nothing.

**Migration.** `dyn fmt --check` now fails on code that passed on preview 8.
Run `dyn fmt DIR` for each module directory and commit the result
separately from other changes. Add `dyn fmt --check DIR` to CI. Write new code
in this layout: two-space indent, one statement per line, a space after commas,
`snake_case` functions and locals, and `PascalCase` types, enum variants, and
constants.

### Editor formatting

LSP formatting returns only the changed lines, returns no edits for an already
formatted or malformed document, and answers requests for unknown documents
with `null` instead of leaving the client waiting.

### Editor completion

Top-level completion no longer analyzes the whole project. A completion request
queued behind edits is answered before project-wide diagnostics run.

### Building the compiler

These affect only people building `dyn` from source:

- `tools/build.py` compiles one object per source file in parallel. Set the
  worker count with `JOBS=n` or `--jobs n`.
- Linker flags in `CPPFLAGS` (`-L`, `-l`, `-Wl,`) are passed to the link step
  only.
- The WASI runtime objects use the `wasm32-wasip1` target.

### Standard library

std was reformatted with the new layout rules. No public API changed.
