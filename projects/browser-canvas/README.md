# Browser canvas

Build a browser-callable Dyn module and serve this directory:

```sh
just --justfile projects/justfile browser
python3 -m http.server 8000 --directory projects/build/browser-canvas
```

Open http://localhost:8000 and apply grayscale. JavaScript supplies pixels in an
arena-backed buffer; Dyn transforms them and calls a JavaScript import. Nothing
allocates an implicit Dyn heap. The global backing buffer lives with the instance.
See [WebAssembly contracts](../../docs/webassembly.md) for imports, exports,
initialization, memory lifetime and trap behavior.
