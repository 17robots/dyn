# Complete bootstrap demo

`compiler/main.dyn` is the directory entry point and calls the implementation in
`compiler/demo.dyn`. Build and run from repository root:

```sh
just
./build/dyn check compiler
./build/dyn build compiler --output build/dyn-demo --emit-ir
./build/dyn-demo
```

Demo exercises primitives, Unicode scalars, structs, arrays and slices, function pointers,
payload enums and exhaustive cases, checked arena/free-list memory, byte copying, reflection,
LIFO defer, standard I/O, monotonic time, and process syscalls. Thread creation and filesystem paths are supported by `std/thread` and `std/fs`;
see the thread and filesystem fixtures and projects for those APIs. The demo is
a small feature sample, not the supported-language checklist.
