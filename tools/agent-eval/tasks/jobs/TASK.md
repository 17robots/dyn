`jobs` reads commands from standard input, one per line, and runs each one as
it arrives, until a line `quit` or the end of input.
- `count PATH` prints `PATH LINES` (the number of newline characters).
- `copy FROM TO` copies the file FROM to TO (created or replaced) and prints
  `copied FROM`. Files may be large; stream them.
- `remove PATH` removes the file and prints `removed PATH`.
- Anything else prints `jobs: unknown command: LINE` to standard error.

A command that fails prints its failure message to standard error, and `jobs`
carries on with the next command. Ignore empty lines. Exit with status 1 if
any command failed or was unknown, else 0.
