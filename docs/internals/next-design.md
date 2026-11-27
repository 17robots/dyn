# Dyn Next-Generation Design & Roadmap

Status: Draft design specification capturing the planned syntax, error-handling, safety, concurrency, and tooling evolution of Dyn beyond preview 40.

## Guiding Principles

Dyn aims to be a single, fast, enjoyable daily-driver systems language—usable for scripts, CLIs, desktop apps, editors, games, web servers, compilers, WebAssembly, and bare-metal firmware—without sacrificing transparency or compile speed.

Core invariants that stay unchanged:

- **One way to do things:** Free functions only (Odin-style—no receiver/method syntax; mutation visibly shows `&`), one pattern construct (`case`), one generic syntax (`<T>`), one error mechanism (`T!E`).
- **No hidden runtime:** No garbage collector, no borrow checker, no traits/interfaces, no OOP, no `Option<T>` / `Result<T, E>` wrapper types, no `async`/`await` coloring, no LLVM dependency.
- **No code is special:** The compiler treats every module identically regardless of path; `std` has zero privileged types or hardcoded compiler hooks.
- **What you read is what runs:** Explicit arenas, mutable locals by default (`x := ...`), no shadowing, zero-is-useful, spatial checks (bounds, nil, alignment) kept in release, and fast (~100 ms) independent native builds.

---

## 1. Grammar & Syntax Cleanups

### Significant newlines (`\n`)
- `\n` terminates statements and top-level declarations (Go/Odin style).
- `\n` is ignored inside `(...)` and `[...]`, and immediately after `,`, `{`, or binary operators (`+`, `-`, `*`, `/`, `%`, `&&`, `||`, `|`, `=>`, etc.).
- Eliminates `same_line()` on `extern fn`, `fn(` no-space sensitivity, speculative multi-line `return` parsing, and `use` trailing-alias lookahead.
- Return types keep Go/current-Dyn style with no `->` required (`fn add(a: i32, b: i32) i32`, `extern fn read(...) isize`).

### Imports (`use`)
- Alias always comes **before** the path (Go style), supporting multiple comma-separated imports on one line with no `as` keyword:
  ```dyn
  use "std/io"
  use col "std/collections", raw "std/io", "std/mem"
  ```

### Literals, headers, and loops
- **Drop trailing-dot floats (`2.` → `2.0`):** Require at least one digit after `.`. No float width suffixes (`2f`); keep `x: f32 = 2.0` and contextual literal adaptation.
- **Delete `tree-sitter-dyn/src/scanner.c`:** Together, dropping `2.` and making `\n` a regular token remove both `TRAILING_FLOAT` and `SAME_LINE`, making the Tree-sitter editor grammar 100% pure `grammar.js`.
- **Raw / multi-line strings:** Backtick raw string literals (`` `...` ``) with no escape processing, spanning multiple lines cleanly.
- **Header struct-literal rule:** Disallow unparenthesized struct literals directly in `if`/`for`/`case` headers (`if p == (Point{ x: 1 }) { ... }`), replacing `src_condition` backtracking/re-parsing with a single parser flag.
- **Labeled `break` and `continue`:** Restore loop labels for clean nested-loop exits:
  ```dyn
  outer: for row in 0..4 {
    for col in 0..4 {
      if row * col == 6 { break outer }
    }
  }
  ```
- **Keep `#reverse` and `#step`** as-is inside `for` headers (`for i in #reverse(#step(0..10, 2))`).

### Length and enum shorthand
- **`xs.len`** on slices and fixed arrays replaces `xs.len`.
- **`.Variant` shorthand** is allowed whenever a single concrete enum type is known (assignments, returns, struct literals, `case` arms). On composed `A | B` unions, variants stay enum-qualified (`FsErr.NotFound(path)`).

---

## 2. Generics (`<T>`) & Compile-Time `case T`

### Unified `<T>` syntax
Replace the 3-way split (`$T`, `T: type`, bare `T`), `#instance`, `Box(i32){` adjacency rules, and call-argument type speculation with one uniform `<T>` syntax:

```dyn
struct Map<K, V> { ... }
enum Slot<T> { Empty, Full(T) }

fn max<T>(a: T, b: T) T {
  if a > b { return a }
  return b
}

fn push<T>(arena: *mem.Arena) *T { ... }

// Calls, literals, and function values:
low := max(width, height)                   // inferred
node := mem.push<Node>(arena)               // explicit
pair := Pair<u8>{ first: 1, second: 2 }     // literal
slot := Slot<i32>.Full(7)                   // enum construction
hash := key_hash<u32>                       // fn value (replaces #instance)
alloc_node := mem.push<Node>                // fn value (replaces #instance)
```

- In expression position, `<` starts type arguments only when followed by a valid type list and a matching `>` followed by `(`, `{`, `.`, or an expression terminator (`,`, `)`, `}`, `\n`). Because Dyn forbids chained comparisons, this never conflicts with `<` / `>`.

### Compile-time `case T` in generics
Allow `case` on a generic type parameter `T`. At instantiation time, the compiler evaluates which arm matches `T` and **only type-checks and lowers that arm**:

```dyn
fn default_hash<K>(seed: u64, key: K) u64 {
  case K {
    str  => { return text_hash(seed, key) }
    bool => { return bool_hash(seed, key) }
    u64  => { return integer_hash(seed, key) }
    u32  => { return integer_hash(seed, key) }
    _    => { #assert(false, "map: use map_with for custom key types") }
  }
}
```

- Eliminates unsafe `#cast(*const u64, &key).*` pointer-punning in `std/container/map`.
- Zero runtime overhead, no traits, no specialization system.
- **`#typeof` stays** as Dyn's zero-macro reflection primitive (`json.object_of`, `enums.from_int`, `fmt`, `#typeof(T).name`, `#assert`).

---

## 3. Error Handling (`T!E` & Composable Enum Unions)

Replaces passed-in `*fail.Status` and the process-global sharded ring buffer (`std/fail/ring*.dyn`) for fallible calls.

### Return-only `T!E`
`!` is valid **only on function return types**—never as a storable wrapper type inside structs, arrays, or slices.

| Return type | Meaning | Success | Failure |
| --- | --- | --- | --- |
| `T` | Always returns `T` | `return x` | — |
| `T!E` | Returns `T`, or error `E` | `return x` | `fail e` |
| `!E` | Void, or error `E` | `return` | `fail e` |
| `T!` | Returns `T`, or bare 1-bit failure | `return x` | `fail` |
| `!` | Void, or bare 1-bit failure | `return` | `fail` |

- Under the hood, `T!E` lowers to a plain tagged return `{ failed: bool, payload: union(T, E) }` (same layout as a payload enum; zero heap, zero unwinding, zero runtime).
- Keep error enum payloads small (`str`, `i32`, `usize`, pointers—never large inline buffers) so return values stay compact.

### `E` is an `enum` or closed union of `enum`s (`A | B`)
- **Ordinary payload enums only:** No separate `error{}` declaration kind and no compiler-owned `ErrorKind`.
- **Allow variant 0 of a payload enum to carry a payload:** Since every Dyn type has a valid zero value, error enums do not need a dummy `None` variant:
  ```dyn
  pub enum FsErr {
    NotFound(str),
    PermissionDenied(str),
    Io(i32),
  }

  pub enum ParseErr {
    BadFormat(usize),
    InvalidUtf8(usize),
  }
  ```
- **Closed `A | B` composition:**
  - Order-independent (`A | B == B | A`), flat (`(A | B) | C == A | B | C`), deduplicated (`A | A == A`).
  - Variants remain scoped to their own enum, so `FsErr.Invalid(str)` and `JsonErr.Invalid(usize)` never collide.
  - **Automatic subset widening:** `FsErr` widens to `FsErr | ParseErr` (and `A | B` widens to `A | B | C`) automatically on `try` and `fail`—zero `From` traits or conversion glue.
  - Signatures remain explicit (`type AppErr = FsErr | ParseErr | NetErr`), preserving fast incremental caching, recursion, function pointers, and syntax-only `dyn docs`.

### `fail`, `try`, `catch`, and `errdefer`
- `try expr` propagates failure immediately, running active `defer`s (and `errdefer`s) in LIFO order.
- `expr catch err { ... }` handles failure in a block (must exit the scope or evaluate to a fallback `T`).
- `expr catch fallback_val` provides a one-line fallback value; `expr catch {}` explicitly ignores a void failure.
- `errdefer stmt` runs cleanup *only* when the function exits via `fail` or a failing `try` (useful in constructors that return acquired resources on success).
- **Streaming builders** (`html.Writer`, `json.Writer`, `fmt.Buffer`) continue recording sticky internal errors so caller code doesn't write `try` on every chunk, exposing one fallible `try w.finish()` at the end.
- **Arenas and lookups stay infallible / zero-safe:** `mem.push<T>(arena)` does not return `T!E`; `map.get` returns `*V` or `nil`; `slice.find` returns index or `.len`. `try` stays localized to OS, I/O, network, and parse boundaries.

---

## 4. Unified `case` Pattern Syntax

All `case` bindings use `Pattern(name)` or `Pattern(*name)`:

- **Payload enums:** `Shape.Circle(r) => { ... }` and `Shape.Circle(*r) => { r.* += 1.0 }`.
  - **`*r` binds a real `*T` requiring `r.*`**, matching `for *p` and removing the `EXP_BINARY(DYN_OP_MUL)` multiplication-parsing hack (fixing `2 * KiB =>` integer patterns).
  - Mirrors enum construction `Shape.Circle(2.0)` and declaration `Circle(f32)`.
- **Enum unions (`FsErr | ParseErr`):** Exhaustive; match individual variants (`FsErr.NotFound(p) =>`), grouped ignored/payload-less variants (`FsErr.Invalid(_), JsonErr.Invalid(_) =>`), or a whole constituent enum (`FsErr(e) =>`).
- **`any` type cases:** `i32(n) =>`, `str(s) =>`, `Vec2(v) =>`, `_ =>` (replacing `i32 n =>`).
- **Compile-time generic type cases:** `case T { str => ..., u64 => ..., _ => ... }`.
- **No `is` keyword:** `case` remains the one pattern-matching construct.

---

## 5. Strings, Slices & Collections

- **`str` shorthand:** Built-in alias for `[]const u8` (clean signatures like `[]str`, `col.Map<str, u32>`).
- **No `u8` special-casing on slices:** Keep `==` strictly O(1) everywhere (no hidden loops on any `[]T`). General runtime slice comparison uses `slice.eql<T>(a, b)` uniformly for `[]u8`, `[]i32`, `[]u32`, etc.
- **`case` on constant text / numeric slices** remains supported via length + discriminating-element dispatch tables.
- **`std/collections`:** Group common arena-backed containers (`Array<T>`, `Map<K, V>`, `Chunk<T>`, `Ring<T>`) with single-line value constructors (`col.array<Task>(arena)`, `col.map<str, u32>(arena)`) to eliminate `array.Array` / `map.Map` stutter and two-step `init` boilerplate.
- **Opt-in `std/mem/heap`:** Explicit general-purpose allocator alongside arenas for the rare workloads with unpredictable per-object lifetimes (still zero hidden allocation).

---

## 6. Builtins Summary

- **Removed:** `#len` (→ `.len`), `#instance` (→ `f<T>`).
- **Added:** `#take(&x)` (moves a `nocopy` value out and resets `x` in place via `#init`).
- **Kept:** `#cast`, `#bitcast`, `#wrapping`, `#sizeof`, `#alignof`, `#offsetof`, `#typeof`, `#min`, `#max`, `#slice`, `#init`, `#assert`, `#panic`, `#load`, `#syscall`, `#reverse`, `#step`, hardware float ops (`#sqrt`, `#floor`, `#ceil`, `#trunc`, `#round`, `#fma`), and file directives (`#target`, `#link`).

---

## 7. Temporal & Concurrency Safety (Without a Borrow Checker)

- **`nocopy` structs (compile-time, 0 runtime cost):**
  - `pub nocopy struct File { ... }` / `pub nocopy struct Arena { ... }` / `pub nocopy struct Mutex { ... }` (works for any user or stdlib type—no hardcoded `std` lists; transitive across containing structs/arrays/enums).
  - Direct copies of stored values (`f2 := f1`, `make_logger(f1)`, `p.*`) are compile errors; pass `&f1` to borrow, or `#take(&f1)` to move out and reset `f1` to its fresh empty value.
- **Intra-function CFG stack-escape checking (compile-time, 0 syntax):**
  - Upgrade `lifetime.h` from straight-line tracking to a fast per-function bitset dataflow pass catching `&local` escapes across branches, loops, structs, and out-parameters.
- **Hardened arena diagnostics (debug & `--check-lifetimes`):**
  - Virtual-memory `PROT_NONE` trapping on rewound/reset/released arena regions for instant hardware traps on use-after-reset/release.
  - Debug thread-affinity check (`owner_thread` in arena header + explicit `mem.arena_transfer(arena)`) catching accidental cross-thread arena sharing immediately.
- **Optional release temporal safety:**
  - Either opt-in `--check-lifetimes` generational arena checks (`{ ptr, gen }` hoisted by SSA CSE, thin 8-byte `*T` kept at C FFI boundaries) and/or an explicit `mem.Ref<T>` generational handle type so hot data keeps 8-byte `*T` by default.
- **Dynamic race detector (`--race`):**
  - Optional TSan-style load/store instrumentation in the SSA backend for test builds (Go `-race` model, zero release cost).
- **Server panic isolation:**
  - Panics stay immediate-abort in CLIs/games; opt-in `fiber.run_isolated` catches panics at a request/worker boundary so one crashed request returns HTTP 500 without killing a multi-tenant server.

---

## 8. Concurrency, Scripting & Toolchain

- **Scoped OS threads & clean channels (`std/thread`, `std/sync`):**
  - `thread.Scope` + `defer thread.scope_join(&scope)` guarantees workers are joined even on early `try`/`fail` exits.
  - Typed `pool.submit<C>(pool, work, &ctx)` (removing `rawptr` from `pool.Task`).
  - Bounded arena-backed `sync.Channel<T>` with `ChanErr { Closed, Full, Empty }`: `send`/`recv` fail cleanly with `.Closed`, `close` is idempotent, nil pointer panics loudly—none of Go's nil-deadlock, fake-zero-on-close, or send/close-panic traps.
- **Opt-in stackful fibers (`std/fiber` over `std/event`):**
  - ~20-line per-arch context switch, virtual-reserved stacks with guard pages, zero `async`/`await` coloring, zero bytes linked when unused. Enables high-concurrency servers with straight-line `try conn.read(buf)` code.
- **Single-file scripting:**
  - `dyn run script.dyn` directly on a single file (no directory required) + shebang support (`#!/usr/bin/env dyn run`).
- **Built-in `dyn test`, `dyn bench`, and `dyn fuzz`:**
  - `*_test.dyn` files excluded from normal builds and run by `dyn test` (`--filter`, `--race`, `--check-lifetimes`), `dyn bench` (warmup + median/p95/arena stats), and `dyn fuzz` (coverage-guided mutation using 1-instruction SSA basic-block edge counters).
- **SSA backend performance:**
  - Continued focus on cross-function inlining, bounds/generation check hoisting, LICM, and explicit `std/simd` codegen to stay within ~5–15% of `clang -O2` while keeping ~100 ms compile times.
- **Decentralized dependencies (future):**
  - Optional URL + SHA-256 pinned dependency entries in `dyn.project` (no central registry).

---

## 9. Phased Implementation Order

1. **Phase 1 — Grammar & Parser Cleanup:**
   - Significant `\n`, drop `2.`, prefix `use` aliases, raw `` `...` `` strings, header struct-literal flag, labeled `break`/`continue`, `xs.len`, `.Variant` shorthand, unified `case` `Pattern(name)`/`Pattern(*name)` (real `*T`).
   - Delete `tree-sitter-dyn/src/scanner.c` and update `tree-sitter-dyn/grammar.js` + `dyn fmt`.
2. **Phase 2 — `<T>` Generics & `case T`:**
   - Switch generics to `<T>`, remove `$T`, `T: type`, `#instance`, and call-arg speculation.
   - Implement compile-time `case T`; clean up `std/container/map` and consolidate `std/collections` with value constructors.
3. **Phase 3 — `T!E` & Composable Enum Unions:**
   - Allow payload on enum variant 0.
   - Implement `A | B` enum unions, return-only `T!E`, `fail`, `try`, `catch`, and `errdefer`.
   - Migrate `std` (`fs`, `io`, `net`, `http`, `encoding/*`, `parse`, `thread`, `event`) off `*fail.Status` and remove `std/fail/ring*.dyn`.
4. **Phase 4 — Safety & Tooling:**
   - `nocopy` structs, CFG stack-escape pass in `lifetime.h`, `PROT_NONE` + thread-affine debug arenas, `dyn run file.dyn`, `dyn test` / `dyn bench` / `dyn fuzz`, and `--race`.
5. **Phase 5 — Concurrency & Performance:**
   - `thread.Scope`, `sync.Channel<T>`, typed `pool.submit<C>`, opt-in `std/mem/heap`, opt-in `std/fiber` + `fiber.run_isolated`, and SSA optimization / `std/simd` passes.
