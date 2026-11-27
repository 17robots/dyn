# 07 · editor

A line editor that runs a script of commands, with unlimited undo and redo.

```sh
dyn run examples/07-editor < examples/07-editor/script.txt
```

Commands: `add TEXT`, `insert N TEXT`, `delete N`, `change N TEXT`, `undo`,
`redo`, `print`.

## What it teaches

- **Writing a generic type.** [stack/stack.dyn](stack/stack.dyn) defines
  `Stack<T>`, a stack for any element type. `pub struct Stack<T>` names the
  parameter; `fn push<T>(s: *Stack<T>, value: T)` infers `T` from its
  arguments. Each use, like `stack.Stack<Edit>`, is checked as ordinary code
  for that type.
- **A local module.** `use "./stack"` imports the `stack` directory next to
  `main.dyn`. Only `pub` declarations are visible outside it, and they are
  always qualified: `stack.push(&editor.undo, e)`.
- **Growing storage in an arena.** When a stack is full, `push` moves its
  items to storage twice the size with `mem.push_array(T, ...)`. The old
  storage stays in the arena until the arena is released; with arenas you
  free lifetimes, not objects.
- **Edits as data.** Each change is an `Edit` value that records what it
  needs to be reversed: a deletion keeps the text it removed. `inverse`
  turns an edit into the edit that undoes it, so undo and redo are each a
  pop, an apply and a push.
- **Missing values.** `stack.pop` returns a `T`; when the stack is empty it
  is T's zero value, safe to read. Check `stack.count` first when the
  difference matters, as `undo` does.
- **Reverse loops.** `for i in #reverse(a..b)` walks a range backwards, to
  open a gap in the line array without overwriting anything.

## Exercises

1. Add `join N`, which joins line N and the next one. What does its inverse
   need to remember?
2. Limit the undo history to 100 edits. Which part of `Stack<T>` changes?
3. Write a generic `fn last<T>(s: *const Stack<T>) *T` that returns `nil` for
   an empty stack, and use it to show the edit `undo` would reverse.
