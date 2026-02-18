# Known Limitations (Current)

- Target support is currently Linux x86_64 only.
- Type checking is intentionally conservative and still incomplete in some advanced cases.
- Return-path analysis is improved but not yet a full control-flow proof system.
- Unreachable code diagnostics currently focus on statements after `break`/`continue` in blocks.
- Iterable `for` currently supports range forms and pointer/slice-style forms (`p[lo..hi]`, named slice bindings, raw pointer sentinel iteration). Array/collection iterator protocol is not implemented yet.
- `match` now has basic overlap/exhaustiveness checks (wildcard placement, duplicate patterns, basic range overlap), but is not yet a full type-driven exhaustiveness engine.
- `extern` function declarations/calls are supported at a basic level, but broader FFI surface/ABI guarantees are not finalized.
- Runtime memory model currently supports local/global slot storage and pointer offsets; heap allocation/lifetime policy is not implemented yet.
- Cache currently uses source/module fingerprints (including toolchain version) and does not yet implement shared content-hash cache storage.
- `--json` is implemented for all top-level commands, but diagnostics payloads are still intentionally minimal and not yet a fully versioned schema.
