# 08 · site

A static site generator: every `pages/NAME.txt` becomes `NAME.html`, plus an
`index.html` that links to every page, sorted by title.

```sh
dyn run examples/08-site -- examples/08-site/pages build/site
```

A page is plain text. The first line is the title, `# ` starts a heading,
`- ` a list item, and other lines are paragraphs separated by blank lines.
[expected/](expected/) holds the HTML the sample pages produce.

## What it teaches

- **Directories.** `fs.list` copies a directory's entries into an arena.
  The order is up to the file system, so the program sorts before it writes
  the index.
- **One status for the whole build.** Listing, reading and writing all take
  the same `*fail.Status`. After the first failure every later step does
  nothing, so `main` checks once, before reporting success, and prints the
  failure (`list missing: no such file or directory`).
- **Paths.** `path.join` and `path.extension` work on text and never touch
  the disk.
- **Safe HTML.** `html.Writer` escapes everything written with `html.text`.
  Markup goes through `html.markup(w, html.trusted("<p>"))`, so text from a
  page, like `<Dyn>` in a title, can never become a tag.
- **Scratch per unit of work.** `build_page` marks the scratch arena and
  defers a rewind. The file's text and the HTML go to scratch and vanish
  when the page is done, so a site of a thousand pages needs no more memory
  than its largest page. What must outlive the page goes to the `keep` arena
  instead: its name and title, and the paths, because a failure borrows its
  path and `main` prints it after the scratch is gone.
- **Sizing for the worst case.** Escaping turns one byte into at most six
  (`&quot;`), so a buffer of six times the input, plus room for tags, always
  fits, and a failed write would be a bug, a `#panic`.
- **Making a directory that may exist.** `fs.make_directory` succeeds when
  the directory is already there; `fs.make_directory_exclusive` would fail.

## Exercises

1. Add `*emphasis*` inside paragraphs, written as `<em>`.
2. Copy every other file in `pages/` (images, stylesheets) to the output
   with `fs.copy_file`.
3. Add a "next page" link at the bottom of each page, following title order.
   What must be known before the first page is written?
