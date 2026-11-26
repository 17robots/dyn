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
    if line.len == 0 { continue }
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
  if program.args.len > 1 {
    path := program.args[1]
    text = fs.read_all(arena, path, mem.MiB) catch err {
      io.eprintln("count: {}: {}", path, err)
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
  every imported name is qualified: `io.println`, `io.IoErr`.
- One statement per line, no semicolons. `x := value` declares, `x: T`
  declares a zero (or field-default) value. No shadowing: pick a new name.
- Struct literals name their type: `Tally{ lines: 1 }`. An enum variant may
  hold a value: `enum Shape { Dot, Circle(f64) }`. Write `Shape.Circle(1.5)`,
  or `.Circle(1.5)` where the enum type is already known. Conversions that
  can lose information need `#cast(T, value)`.
- `str` is `[]const u8`: bytes and a length. `[N]T` is an array, `[]T` a
  slice (`xs.len`), `*T` a pointer (`p.*` reads it; fields auto-deref).
  Raw strings use backticks.
- `for` is the only loop: `for cond`, `for {}`, `for i in 0..n`,
  `for value in values`, `for *value in values`, `for value, i in values`.
  A label names a loop for `break` and `continue`: `outer: for { break outer }`.
- `case` arms are `pattern => { ... }`. Enum cases list every variant or
  have `_`; integer and text cases always have `_`. A payload is read only
  in an arm: `Shape.Circle(radius) => { ... }`, or `Shape.Circle(*radius)`
  for a pointer to it.
- Generics use `<T>`: `fn max<T>(a: T, b: T) T` infers `T` from arguments;
  `mem.push<Node>(arena)` names it. Inside a generic, `case T { ... }` picks
  code per type at compile time.
- `defer` runs at block exit. A panic ends the program; it is for bugs.
  `panic.assert(condition, "message")` (`std/panic`) checks one at run time,
  in every build; `#assert` checks constants at compile time.

## Failure: `T!E`, `try` and `catch`

1. A function that can fail returns `T!E`: a `T`, or an error `E`, an enum
   (or a union of enums, `FsErr | ParseErr`). `!E` returns nothing on
   success. `fail .NotFound` fails; `return value` succeeds.
2. `try f()` passes a failure up to the caller (running `defer` and
   `errdefer`); the caller's error type must include it. `f() catch err { ... }`
   handles it: the block must leave with `return`, `fail`, `break`,
   `continue` or `#panic`. `f() catch fallback` gives a value instead, and a
   void call can `catch {}`.
3. `case err { .NotFound => { ... } _ => { ... } }` reacts to one kind.
   `io.IoErr` is the error of `std/io`, `std/fs` and `std/process`;
   `io.println("{}", err)` prints its meaning, such as "not found". Name the
   path in your message: the error does not carry it.

Iterators return their value and set `ended` on their state at the end:
`entry := try fs.directory_next(&directory)`, then
`if directory.ended { break }`. Cleanup cannot fail (`fs.close(&file)`,
`mem.arena_release(arena)`).

Decoders fail with `parse.ParseErr` and the byte offset where the input went
wrong. A builder into fixed storage, such as `fmt.Buffer`, keeps its first
overflow: check `fmt.overflowed(&buffer)` once, or let `finish` fail.

## Memory: arenas only

- `arena := mem.arena_alloc(0)` then `defer mem.arena_release(arena)`.
  Fixed storage: `mem.arena_from_buffer(storage[..])`.
- `mem.push(T, arena)`, `mem.push_array(T, arena, n)` (zeroed),
  `mem.push_bytes(arena, n)` (uninitialized).
- Temporary work: `mark := mem.arena_mark(arena)`,
  `defer mem.arena_rewind(arena, mark)`. Per loop or request:
  `mem.arena_reset(arena)`.
- Running out panics. Functions that allocate take the arena first:
  `fs.read_all(arena, path, maximum)`.
- Growing lists: `std/container/array`; bytes: `std/bytes/builder`.

## Where things are

Qualify with the module's last path element: `use "std/encoding/json"` gives
`json.parse`. `dyn docs MODULE` lists everything in one.

| Module | Use it for |
| --- | --- |
| `std/io` | `println`, `eprintln`, `stdin()`, `stdout()`, `read`, `write`, `copy`, `IoErr` |
| `std/bufio` | `reader(io.stdin(), storage)`, `read_line`, buffered `writer` |
| `std/fs` | `open`, `create`, `read`, `write`, `close`, `read_all`, `write_all`, `list`, `remove`, `rename`, `metadata`, `make_directory`, `atomic_begin`/`atomic_commit` |
| `std/process` | `start().args`, `environment`, `spawn`, `wait` |
| `std/encoding/json` | `parse`, `get<T>(value, key)`, `is_string`, `is_number`, `writer` |
| `std/strings` | `format`, `split`, `join`, `trim`, `clone`, `parse` |
| `std/bytes` | `equal`, `find`, `contains`, `starts_with`, `ends_with`, `count_occurrences` |
| `std/path` | `join`, `basename`, `extension` |
| `std/collections` | `array<T>(arena)`, `map<K, V>(arena)`, `ring<T>(arena, n)` |
| `std/thread`, `std/sync` | `scope`/`scope_spawn`/`scope_join`, `channel<T>`, mutexes |

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
| `.{ .x = 1 }` | `Point{ x: 1 }` |
| `x as u32`, `@intCast(x)`, `(u32)x` | `#cast(u32, x)` |
| `file.close()`, methods | `fs.close(&file)` |
| `f()?`, `err != nil` | `try f()`, `f() catch err { ... }` |
| `malloc`, `Box::new`, `allocator.create` | `mem.push(T, arena)` |
| `Vec<T>`, `ArrayList(T)`, `append` | `col.array<T>(arena)`, `col.push` (`std/collections`) |
| `fmt.Printf("%d", n)`, `println!("{}", n)` | `io.println("{}", n)` |
| `import "fmt"`, `@import("std")` | `use "std/fmt"` |
