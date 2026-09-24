# Profiling and dynamic libraries

`std/profile` records monotonic spans into caller-owned `[]profile.Event` storage. `begin` borrows
the name; it must outlive recorded events. `end` returns `false` and increments `dropped` when full.
No allocation, I/O, global state, or thread synchronization occurs.

`std/dynlib` is a thin POSIX loader adapter for Linux x86-64. `open` and `symbol` copy names into a
bounded 4096-byte stack buffer. Handles must be closed explicitly. Symbols and error text are
borrowed; error text dies at the next loader call. Programs must explicitly link the platform libc
(or `libdl` where required), preserving Dyn's no-implicit-library rule.
