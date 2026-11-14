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
- **Results.** `fs.open(name)` returns `{value, failure}`. Check it with
  `io.failed(opened.failure)`; `failure.kind` is a portable category such as
  `io.Kind.NotFound`. The value is safe to read even on failure.
- **Owning a handle.** A `fs.File` is an OS resource with one owner.
  `fs.take(&opened.value)` moves it out of the result, and `defer
  fs.close(&file)` closes it when the loop iteration ends, however it ends.
  `dyn vet` warns about copying a handle instead.
- **Streaming through a seam.** `count_reader` takes an `io.Reader`, so the
  same code reads a file (`fs.reader(&file)`) and standard input
  (`io.stdin()`). It reads 64 KiB at a time into one stack buffer, so a file
  of any size uses the same memory.
- **State across chunks.** A word can be cut in two by a chunk boundary, so
  `Counts.in_word` carries that state from one chunk to the next.
- **Bit tests.** UTF-8 continuation bytes look like `10xxxxxx`;
  `(byte & 0xC0) != 0x80` counts the others. Mixing `&` with `!=` needs
  parentheses.
- **Building text in a buffer.** `fmt.buffer(storage[..])` writes into stack
  storage. Its writes are sticky: once one does not fit, the rest do nothing,
  and `row.failed` is checked once at the end.

## Exercises

1. Add `-l`, `-w` and `-c` options that print only one column.
2. Count the longest line, as `wc -L` does.
3. Read `count_reader`'s loop again and explain why the bytes of the final
   chunk are counted before `failure` and `ended` are looked at.
