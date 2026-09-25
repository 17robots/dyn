# WASI command

```sh
just --justfile projects/justfile wasi
node tools/run-wasi.mjs projects/build/wasi-hello.wasm hello world
```

The command allocates an arena, obtains arena-owned argument slices, prints through
`std/io` and `std/terminal`, then releases the arena. This targets WASI Preview 1;
no browser DOM, native shared libraries, sockets or threads are implied.
