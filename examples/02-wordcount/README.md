# 02 · wordcount

A clone of `wc`: count lines, words, characters and bytes in files, or in
standard input when no file is named.

```sh
dyn run examples/02-wordcount -- examples/02-wordcount/poem.txt examples/02-wordcount/words.txt
dyn run examples/02-wordcount < examples/02-wordcount/poem.txt
```

## What it teaches

- **Program arguments.** `program := process.start()` on main's first line
  gives `program.args` (the program's own path first) and `program.arena`,
  an arena that lives as long as the program.
- **Exit codes.** `fn main() i32` returns the process exit status.
- **Failures with `try` and `catch`.** `count_file` returns `!io.IoErr`:
  nothing, or why it failed. `try` passes a failure from `fs.open` or
  `io.read` up to the caller. `main` catches each file's failure on its own,
  so one that cannot be read is reported (`missing.txt: not found`) and the
  rest still count.
- **Closing a handle once.** A `fs.File` is a plain value naming an OS
  resource. `defer fs.close(&file)` closes it when `count_file` returns,
  however it returns; closing a file that never opened does nothing.
- **Streaming through a seam.** `count_reader` takes an `io.Reader`, so the
  same code reads a file (`fs.reader(&file)`) and standard input
  (`io.stdin()`). It reads 64 KiB at a time into one stack buffer, so a file
  of any size uses the same memory.
- **State across chunks.** A word can be cut in two by a chunk boundary, so
  `Counts.in_word` carries that state from one chunk to the next.
- **Bit tests.** UTF-8 continuation bytes look like `10xxxxxx`;
  `(byte & 0xC0) != 0x80` counts the others. Mixing `&` with `!=` needs
  parentheses.
- **Building text in a buffer.** `fmt.buffer(storage[..])` writes
  into stack storage. Once a write does not fit, the rest do nothing, and
  `fmt.overflowed(&row)` is checked once at the end.

## Exercises

1. Add `-l`, `-w` and `-c` options that print only one column.
2. Count the longest line, as `wc -L` does.
3. `count_reader` has no `if` for failures. Explain how its loop ends when
   a read fails, and where the failure gets reported.
