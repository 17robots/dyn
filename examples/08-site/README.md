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

- **Directories.** `fs.open_directory` reads entries into a buffer you give
  it, and `fs.directory_next` returns one entry at a time. An entry's name
  borrows that buffer, so kept names are copied. The order is up to the
  file system, so the program sorts before it writes the index.
- **Paths.** `path.join` and `path.extension` work on text and never touch
  the disk.
- **Safe HTML.** `html.Writer` escapes everything written with `html.text`.
  Markup goes through `html.markup(w, html.trusted("<p>"))`, so text from a
  page, like `<Dyn>` in a title, can never become a tag.
- **Scratch per unit of work.** `build_page` marks the scratch arena and
  defers a rewind. The file's text, the HTML and the paths all go to scratch
  and vanish when the page is done, so a site of a thousand pages needs no
  more memory than its largest page. What must outlive the page (its name
  and title) goes to the `keep` arena instead.
- **Sizing for the worst case.** Escaping turns one byte into at most six
  (`&quot;`), so a buffer of six times the input, plus room for tags, always
  fits, and a failed write would be a bug, a `#panic`.
- **Failures you expect.** `fs.make_directory` failing with
  `io.Kind.AlreadyExists` is fine; any other failure stops the program.

## Exercises

1. Add `*emphasis*` inside paragraphs, written as `<em>`.
2. Copy every other file in `pages/` (images, stylesheets) to the output
   with `fs.copy_file`.
3. Add a "next page" link at the bottom of each page, following title order.
   What must be known before the first page is written?
