# 01 · Game of Life

A board of cells, each alive or dead. Every generation, a live cell with two
or three live neighbours survives, a dead cell with exactly three comes
alive, and every other cell dies. The board's edges wrap around, so the
glider in the corner travels forever.

```sh
dyn run examples/01-life
```

The program prints five generations. Compare with [session.txt](session.txt).

## What it teaches

- **Imports and output.** `use "std/io"` binds the module `io`, and
  `io.println("{} alive", n)` fills each `{}` with the next argument.
- **Constants.** `const Width := 12` is built from a literal, so it adapts to
  whatever integer type each use needs: an array length, a `usize` index.
- **Structs and fixed arrays.** `Board` holds `[Height][Width]bool`. A fixed
  array is a value: `board = step(board)` copies every cell, and a
  declaration without a value (`next: Board`) starts at zero.
- **Value and pointer parameters.** `neighbours(board: Board, ...)` reads
  its own copy; `load(board: *Board, ...)` changes the caller's board through
  a pointer. Fields reach through pointers: `board.cells`, never `board.*.cells`.
- **Loops.** `for dy in 0..3` counts `0, 1, 2`. `for row, y in board.cells`
  gives each element and its `usize` index. `for _ in 0..Generations`
  repeats without naming the counter.
- **`case`** on a byte, with `_` for everything else.
- **Overflow is a bug.** `(x + Width + dx - 1) % Width` adds before it
  subtracts, so a `usize` never goes below zero. In a debug build, arithmetic
  that overflows stops the program with `overflow.ok` instead of quietly
  wrapping.
- **`#panic`** for a broken invariant: a pattern row of the wrong width is a
  bug in the program, not an error to handle.

## Exercises

1. Change `pattern` to start with a different shape, such as an R-pentomino.
2. Stop early when a generation is the same as the one before it. Two
   `Board` values can be compared field by field, or cell by cell.
3. Count the generations until the population stops changing.
