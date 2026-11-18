Write a command-line tool in Dyn as `main.dyn` in the current directory.
Every message about a failure is one line on standard error that starts with
the tool name and says what went wrong, including the path involved (for
example `move: open notes.txt: no such file or directory`). Panics are only
for bugs. Use only the Dyn standard library.
