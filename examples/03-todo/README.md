# 03 · todo

A task list kept in a text file, one task per line.

```sh
dyn run examples/03-todo -- add buy oat milk
dyn run examples/03-todo -- list
dyn run examples/03-todo -- done 1
```

Tasks are saved in `./todo.txt`, or the file named by `TODO_FILE`. See
[session.txt](session.txt) for a whole session.

## What it teaches

- **A module of several files.** `main.dyn` runs commands, `task.dyn` defines
  a task and its line format, `store.dyn` loads and saves. Every file in the
  directory shares one namespace, so no file imports another. Each file
  imports the modules it uses itself.
- **Enums.** `State { Open, Done }`: the first variant is the zero value, so
  a zero `Task` is an open task. `case` must name every variant.
- **`case` on text** compares bytes: `case command { "list" => {...} _ => {...} }`.
  A text case always needs `_`.
- **A growing array.** `array.Array(Task)` keeps its items in an arena;
  `array.push` adds, `array.pop` removes the last one and says whether it found one.
- **A parser that fails.** `parse_task` takes a `*fail.Status` like anything
  else that can fail; `parse.malformed` records what went wrong and the byte
  offset. `load` gives each line its own status, so its message can name the
  line. `parse.u64_decimal` reports bad numbers the same way.
- **A status for loading and saving.** `load` and `save` take a
  `*fail.Status`; `main` checks it once after each. Inside `save`, a failed
  write makes the rename do nothing, so no check sits between them.
- **Reacting to one kind of failure.** `load` reads with a status of its own
  and treats `fail.Kind.NotFound` as an empty list; any other failure goes on
  to the caller with `fail.set`.
- **Borrowing the file's text.** `fs.read_all` loads the whole file into the
  arena, and every `Task.text` is a slice of that text. Nothing is copied
  and nothing is freed one task at a time.
- **Environment variables.** `process.environment_or(arena, "TODO_FILE", "todo.txt")`
  gives the variable's value, or the fallback when it is unset.
- **Saving safely.** `save` writes a temporary file, then `fs.rename` moves
  it over the old one, so a crash never leaves half a list.
- **Absence is not failure.** A missing `todo.txt` is an empty list, and
  `task_index` returns `count` (one past the end) for a bad number, the same
  miss value every `find` in the standard library uses.

## Exercises

1. Add `todo undo N` to reopen a done task.
2. Add a priority: `todo add ! call the plumber` marks a task urgent, saved
   as `[!]`, and `list` shows urgent tasks first.
3. Make `load` report every bad line instead of stopping at the first.
