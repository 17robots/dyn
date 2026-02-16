# Known Limitations (Current)

- Target support is currently Linux x86_64 only.
- Type checking is intentionally conservative and still incomplete in some advanced cases.
- Return-path analysis is improved but not yet a full control-flow proof system.
- Unreachable code diagnostics currently focus on statements after `break`/`continue` in blocks.
- Cache fingerprints are source/module based and do not yet pin toolchain version.
- `--json` is currently implemented for `check`, `build`, and `clean` (not `run`).
