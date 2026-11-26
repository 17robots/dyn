# 04 · journal

An interactive note keeper that reads commands from standard input.

```sh
dyn run examples/04-journal < examples/04-journal/commands.txt
dyn run examples/04-journal          # then type: note hello, list, stats, undo
```

## What it teaches

This project is about **lifetimes**: for every piece of data, ask how long it
must live, and put it where it lives that long.

| Storage | Lives until | Holds |
| --- | --- | --- |
| `line: [512]u8` on the stack | the next line is read | the command being run |
| `frame` arena | `mem.arena_reset(frame)` after every command | lowercase copies for `find` |
| `permanent` arena | `mem.arena_release` when main returns | the notes |

- **Copy what outlives its storage.** A note's text arrives in `line`, which
  the next read overwrites, so `add_note` copies it into the permanent arena
  with `strings.clone`. Keeping the slice instead would show the wrong text
  later.
- **Reset per iteration.** Everything a command puts in `frame` disappears in
  one step when the command ends. However long the session, `stats` shows
  the frame's peak stays the size of one command.
- **Undo by rewinding.** An arena frees in reverse order. Each note records
  `mem.arena_mark` before it is pushed, so `undo` rewinds to that mark and
  gives back exactly that note's memory. Read what you need from the note
  first: after the rewind its pointers are stale.
- **Arenas are explicit.** `mem.arena_alloc(0)` creates one with the default
  block size (address space only; pages cost memory when touched), and
  `defer mem.arena_release(...)` returns it. `mem.push(Note, arena)` gives a
  zeroed `*Note` with its field defaults.
- **Linked lists in an arena** need no individual frees: `Note.previous`
  points at the older note, and `nil` ends the list.
- **Reading lines.** `bufio.reader` buffers standard input, and
  `bufio.read_line` returns the next line, borrowed from that buffer until
  the next read. `reader.ended` turns true at the end of the input. A line
  longer than the buffer fails with `Capacity`, which `main` picks out with
  `case`; the next read carries on after that line.

## Exercises

1. Add `edit TEXT`, which replaces the newest note. Where should the new
   text go, and what happens to the old text's memory?
2. Make `find` print matches oldest first without allocating.
3. Add `save FILE`, writing every note to a file, using the frame arena for
   the text you build.
