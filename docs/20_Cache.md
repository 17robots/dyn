# Dyn Build Cache

Dyn stores module object fingerprints under `<work-dir>/.dyn_cache/`.

## What is fingerprinted

Per module fingerprint currently includes:
- module name
- codegen target (`Options.target`)
- artifact kind (`Options.kind`)
- codegen strategy (`Options.strategy`)
- Zig toolchain version (`builtin.zig_version`)
- each module file path, file size, and mtime

## Reuse rules

A cached module object is reused only when:
- object file exists
- module fingerprint manifest exists
- stored fingerprint exactly matches current fingerprint

Otherwise the module object is rebuilt.

## Dependency invalidation

If a module is marked dirty, all importers are marked dirty via reverse dependency propagation.

Covered scenarios in tests:
- source content change
- rename of module file
- deletion of module file
- move of module file out of module directory

## Current limitations

- Fingerprints use file `mtime` + size + path; unusual timestamp behavior can reduce precision.
- No cross-workdir shared cache yet.
- Fingerprints are source/module-level (not content-hash-based).
