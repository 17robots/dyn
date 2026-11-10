# Language rules, 2026-11-08

Most old code fails to compile with an error that names the fix. Work through
the errors, then check the cases at the end, which still compile.

| Old | New |
| --- | --- |
| `is i64 n => { ... }` | `i64 n => { ... }` |
| `is Point p => { ... }` | `Point p => { ... }` |
| `flags & mask == 0` | `(flags & mask) == 0` |
| `a == b == c` | `(a == b) == c` |
| `_ = io.println(io.stdout(), "n {}", n)` | `io.println("n {}", n)` |
| `_ = io.println(io.stderr(), "oops")` | `io.eprintln("oops")` |
| `result := io.println(writer, "x")` | `result := io.println_to(writer, "x")` |
| `io.Result` (a transfer count) | `io.Transfer` |
| `box: Box(i32) = {value: 1}` | still fine; `Box(i32){value: 1}` also works |
| zero, then set fields by hand | `struct S { n: i32 = 4 }` |
| translation table for fixed tags | `enum(i32) Errno { Ok = 0, NoEnt = 2 }` when the tags never change |

## Compiles, but check

- A nested block may now shadow an outer name. Code that relied on the old
  error to catch a reused name should be read again.
- `for i in 0..n` takes its type from the first typed use of `i` in the body.
  A loop that used `i` as a `usize` index first and an `i32` later keeps `usize`.
- An inferred constant built from literals (`const LIMIT := 64`) adapts to each
  use. Give it a type (`const LIMIT: u32 = 64`) to keep the old fixed type.
- Literals passed as `any` are `i32`, `f64` and `[]const u8`.
- `mem.push` and `mem.try_push` write field defaults. `mem.push_array` stays
  zeroed; use `mem.push_array_init` for defaults on every element.
- A body-less declaration's return type must start on the line of its `)`.
- `panic.set_handler` runs once after cleanups. A panic still ends the program
  with exit code 101. On Wasm a panic traps at once and the handler does not run.
