# Dyn Tree-sitter grammar

Build and release from this checkout; no compiler or parent justfile is needed.

Build commands require `just`, Python 3, and Bash. Set configuration through
environment variables before the command.

```sh
just generate        # requires Tree-sitter CLI pinned in .tree-sitter-version
just test            # corpus, reproducible generated files, native highlight queries
just release         # static/shared grammar libraries plus tests
just package         # standalone source tarball, manifest and checksum in build/dist
PREFIX=/usr/local DESTDIR=/path/to/staging just install
```

`CC`, `CFLAGS`, `CPPFLAGS`, `TS`, `PREFIX`, `DESTDIR`, `BUILD` and `DIST` are
configurable. Native highlight tests require Tree-sitter runtime development
headers/library. Library builds use the checked-in generated parser; changing
`grammar.js` or `tree-sitter.json` regenerates it with the pinned CLI.

The package includes its justfile, generated C sources/headers, bindings, corpus,
editor queries and release tools. It can be extracted and built independently.
The library install retains its versioned soname and pkg-config interface.

Combined-workspace editor checks are deliberately separate:

```sh
WORKSPACE=.. just check-workspace
WORKSPACE=.. just editor-grammar
WORKSPACE=.. just verify-published-grammar
```

`editor-grammar` refreshes local Zed files/Wasm, not remote pins or provenance.
`check-workspace` verifies matching local files and recorded hashes.
`verify-published-grammar` reads remote pinned files; none of these publishes a
release. Update and verify editor pins as part of the separate editor release.
