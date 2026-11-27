# Learn Dyn by building programs

Nine small, complete programs, each one a real tool you can run, read and
change. They go in order: each project uses what the earlier ones taught and
adds a few new ideas. Every program is tested on each release, so what you
read here compiles and behaves as shown.

Run any of them from the repository root:

```sh
dyn run examples/01-life
dyn run examples/02-wordcount -- examples/02-wordcount/poem.txt
dyn run examples/05-calc < examples/05-calc/input.txt
```

Arguments after `--` go to the program. `dyn build DIR --output NAME` makes an
executable instead; add `--release` for an optimized build. Each project's
`session.txt` shows a recorded run: the commands, what they printed, and the
exit code when it is not 0.

| Project | You build | You learn |
| --- | --- | --- |
| [01-life](01-life/README.md) | Conway's Game of Life | constants, structs, fixed arrays, functions, loops, `for value, index`, pointers to mutate |
| [02-wordcount](02-wordcount/README.md) | a `wc` clone | program arguments, files, a failure per file, `io.Reader`, `defer`, exit codes, `fmt.Buffer` |
| [03-todo](03-todo/README.md) | a task list saved to a file | modules of several files, enums, `case` on text, `array.Array`, a parser that fails, your own error enum, atomic saves |
| [04-journal](04-journal/README.md) | an interactive note keeper | arenas and lifetimes: permanent, per-command frame, undo by rewinding, `bufio` input |
| [05-calc](05-calc/README.md) | a calculator with variables | tagged enums, recursive descent parsing, trees in an arena, sticky failures, `map.Map` |
| [06-ledger](06-ledger/README.md) | an expense report from CSV | `distinct type`, `std/encoding/csv`, totals in a map, `sort.sort_by`, function values, tables |
| [07-editor](07-editor/README.md) | a line editor with undo and redo | writing a generic type, `<T>`, a local module, edits as data |
| [08-site](08-site/README.md) | a static site generator | directories, paths, HTML escaping, scratch memory per page |
| [09-primes](09-primes/README.md) | a multi-threaded prime counter | threads with typed context, atomics, sharing work without locks, `join` |

[The tour](tour/main.dyn) is different: one file that touches every part of
the language, as a reference to skim before or after the projects.
`box-viewer` is a larger demo of the `std/ui` toolkit and needs a window
system.

## How Dyn programs are shaped

A few rules hold in every project, so it pays to know them up front.

- **A directory is a module.** Every `.dyn` file in it shares one namespace;
  a program's entry point is `fn main()` in `main.dyn`. Imported names are
  always qualified: `io.println`, `mem.push`.
- **Memory is explicit.** Nothing allocates behind your back. Small things
  live on the stack; everything else goes into an arena you create, pass and
  release, chosen by how long the data must live.
- **Failure is a value.** A call that can fail returns `T!E`: its value, or
  an error enum such as `io.IoErr`. `try` passes a failure up, and `catch`
  handles it where you can do something about it. A broken invariant is a
  bug: `#panic` stops the program, and there is no recovery.
- **No hidden costs.** No exceptions, garbage collector or implicit
  conversions that lose information. Array bounds and nil pointers are always
  checked; integer arithmetic wraps unless you build with `--check-overflow`.

## Where to go next

- [Idiomatic Dyn](../docs/guide/idiomatic-dyn.md): how to write clear, correct Dyn
- [Language reference](../docs/guide/language.md): the exact rules
- [Standard library](../docs/guide/std.md); `dyn docs std/io` prints any module's API
- [Memory and ownership](../docs/guide/memory.md)
