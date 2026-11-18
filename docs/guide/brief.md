# Dyn in brief

One page for writing Dyn without guessing. `dyn guide rules` lists every
language rule; `dyn guide` lists the other topics.

## Work loop

```sh
dyn docs std/fs            # public declarations of a module (--json for tools)
dyn check app              # type-check; --diagnostics json for tools
dyn fix app                # apply the fixes check reports, then check again
dyn run app -- arguments   # build and run; dyn build app --release for a binary
```

A diagnostic's `fix:` line is safe to apply as written; `dyn fix` applies
those. A `suggestion:` line is a guess to check by hand.

## A whole program

```dyn
use "std/fail"
use "std/fs"
use "std/io"
use "std/mem"
use "std/process"
use "std/strings"

struct Tally {
  lines: usize,
  words: usize,
}

fn count(arena: *mem.Arena, text: []const u8) Tally {
  tally := Tally{}
  for line in strings.split(arena, text, "\n") {
    if #len(line) == 0 { continue }
    tally.lines += 1
    in_word := false
    for byte in line {
      space := byte == ' ' || byte == '\t'
      if !space && !in_word { tally.words += 1 }
      in_word = !space
    }
  }
  return tally
}

fn main() i32 {
  program := process.start()
  arena := mem.arena_alloc(0)
  defer mem.arena_release(arena)
  text: []const u8 = "one two\nthree\n"
  if #len(program.args) > 1 {
    status: fail.Status
    text = fs.read_all(arena, &status, program.args[1], mem.MiB)
    if status.failed {
      storage: [256]u8
      io.eprintln("count: {}", fail.describe(storage[..], status.failure))
      return 1
    }
  }
  tally := count(arena, text)
  io.println("{} lines, {} words", tally.lines, tally.words)
  return 0
}
```

## Shape

- A directory is a module. Its `.dyn` files share one namespace; `main.dyn`
  holds `fn main()` or `fn main() i32`. Imports are `use "std/io"` and
  every imported name is qualified: `io.println`, `fail.Status`.
- One statement per line, no semicolons. `x := value` declares, `x: T`
  declares a zero (or field-default) value. No shadowing: pick a new name.
- Types are written in full: `Shape.Circle(1.5)`, `Tally{ lines: 1 }`,
  never `.Circle` or `.{ }`. An enum variant may hold a value:
  `enum Shape { Dot, Circle: f64 }`. Conversions that can lose information need
  `#cast(T, value)`.
- `[]const u8` is a string: bytes and a length. `[N]T` is an array,
  `[]T` a slice, `*T` a pointer (`p.*` reads it; fields auto-deref).
- `for` is the only loop: `for cond`, `for {}`, `for i in 0..n`,
  `for value in values`, `for *value in values`, `for value, i in values`.
  No labels; `break` and `continue` act on the innermost loop.
- `case` arms are `pattern => { ... }`. Enum cases list every variant or
  have `_`; integer and text cases always have `_`. A payload is read only
  in an arm: `Shape.Circle radius => { ... }`.
- Generics: `fn max(a: $T, b: $T) T` infers `T` from arguments;
  `fn make(T: type, ...)` takes it first, as in `mem.push(Node, arena)`.
- `defer` runs at block exit. A panic ends the program; it is for bugs.
  `panic.assert(condition, "message")` (`std/panic`) checks one at run time,
  in every build; `#assert` checks constants at compile time.

## Failure: one shape everywhere

1. A call that can fail takes `&status` (a `fail.Status`) and returns its value.
2. A lookup always returns a usable value: zero or empty when it is not
   there, with `NotFound` on the status, or `InvalidInput` when it is there
   but wrong (a string where a number goes):
   `port := json.get(i64, &status, root, "port")`. Read an optional value
   with a status of its own, so a missing one stops nothing else.
   Iterators return their value too, and set `ended` on their state at the
   end: `line := bufio.read_line(&status, &reader)`, then
   `if reader.ended { break }`.
3. Check `status.failed` before you act on what you got. After the first
   failure every call given that status does nothing and returns zero, so
   one check at the end of a unit of work is enough.

`fail.describe(storage, status.failure)` gives "open app.json: no such file
or directory". Cleanup takes no status (`fs.close(&file)`,
`mem.arena_release(arena)`), so it works after a failure; other cleanup that
can fail gets a fresh status.

## Memory: arenas only

- `arena := mem.arena_alloc(0)` then `defer mem.arena_release(arena)`.
  Fixed storage: `mem.arena_from_buffer(storage[..])`.
- `mem.push(T, arena)`, `mem.push_array(T, arena, n)` (zeroed),
  `mem.push_bytes(arena, n)` (uninitialized).
- Temporary work: `mark := mem.arena_mark(arena)`,
  `defer mem.arena_rewind(arena, mark)`. Per loop or request:
  `mem.arena_reset(arena)`.
- Running out panics. Functions that allocate take the arena first:
  `fs.read_all(arena, &status, path, maximum)`.
- Growing lists: `std/container/array`; bytes: `std/bytes/builder`.

## Where things are

Qualify with the module's last path element: `use "std/encoding/json"` gives
`json.parse`. `dyn docs MODULE` lists everything in one.

| Module | Use it for |
| --- | --- |
| `std/io` | `println`, `eprintln`, `stdin()`, `stdout()`, `read`, `write`, `copy` |
| `std/bufio` | `reader(io.stdin(), storage)`, `read_line`, buffered `writer` |
| `std/fs` | `open`, `create`, `read`, `write`, `close`, `read_all`, `write_all`, `list`, `remove`, `rename`, `metadata`, `make_directory`, `atomic_begin`/`atomic_commit` |
| `std/process` | `start().args`, `environment`, `spawn`, `wait` |
| `std/encoding/json` | `parse`, `get(T, &status, value, key)`, `is_string`, `is_number`, `writer` |
| `std/strings` | `format`, `split`, `join`, `trim`, `clone`, `parse` |
| `std/bytes` | `equal`, `find`, `contains`, `starts_with`, `ends_with`, `count_occurrences` |
| `std/path` | `join`, `basename`, `extension` |
| `std/container/array`, `std/container/map` | growing arrays, hash maps |
| `std/fail` | `Status`, `describe`, `invalid`, `Kind` |

## Not X, write Y

From Go, Rust, Zig and C:

| Not | Write |
| --- | --- |
| `let x = 1`, `var x = 1`, `let mut x = 1` | `x := 1` |
| `let x: i32 = 1`, `var x: i32 = 1` | `x: i32 = 1` |
| `while cond { }`, `loop { }` | `for cond { }`, `for { }` |
| `for (i = 0; i < n; i++)` | `for i in 0..n { }` |
| `x++`, `x--` | `x += 1`, `x -= 1` |
| `cond ? a : b` | `if cond { x = a } else { x = b }` |
| `if x { }` on a number or pointer | `if x != 0 { }`, `if p != nil { }` |
| `a + b` on strings | `strings.format(arena, "{}{}", a, b)` |
| `values` where a slice goes | `values[..]` |
| `.Variant`, `.{ .x = 1 }` | `Enum.Variant`, `Point{ x: 1 }` |
| `x as u32`, `@intCast(x)`, `(u32)x` | `#cast(u32, x)` |
| `file.close()`, methods | `fs.close(&file)` |
| `try f()`, `f()?`, `err != nil` | `f(&status)`, then `if status.failed` |
| `malloc`, `Box::new`, `allocator.create` | `mem.push(T, arena)` |
| `Vec<T>`, `ArrayList(T)`, `append` | `std/container/array` |
| `fmt.Printf("%d", n)`, `println!("{}", n)` | `io.println("{}", n)` |
| `break outer` | a flag, or move the inner loop into a function |
| `import "fmt"`, `@import("std")` | `use "std/fmt"` |
