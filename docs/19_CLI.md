# Dyn CLI Reference

## Commands

- `dyn check [entry.dyn] [--std-dir dir] [--json]`
- `dyn build [entry.dyn] [-o out] [--emit-obj|--emit-asm] [--work-dir dir] [--std-dir dir] [--json]`
- `dyn run [entry.dyn] [--work-dir dir] [--std-dir dir] [--json] [-- arg ...]`
- `dyn clean [--work-dir dir] [--json]`

## Exit Codes

- `0`: success
- `1`: CLI usage error, frontend/build failure, or runtime process failure mode not represented by normal exit
- `run`: if compiled program exits normally, dyn exits with the same program exit code

## Machine-Readable Output

`--json` is supported on `check`, `build`, `run`, and `clean`.

## Std Import Fallback

- `--std-dir <dir>` configures a fallback root for `use "std/..."` imports.
- Resolution order is: local relative import first, then `--std-dir` fallback.

Examples:

```json
{"schema":"dyn-cli.v1","command":"check","entry":"main.dyn","graph_errors":0,"scope_errors":0,"resolve_errors":0,"semantic_errors":0,"can_codegen":true,"diagnostics":[]}
```

```json
{"schema":"dyn-cli.v1","command":"build","entry":"main.dyn","out":"a.out","work_dir":".dyn_build","emit":"exe","ok":true,"diagnostics":[]}
```

```json
{"schema":"dyn-cli.v1","command":"run","entry":"main.dyn","work_dir":".dyn_build","exe":".dyn_build/run.out","exit_code":0,"ok":true,"build_diagnostics":[]}
```

```json
{"schema":"dyn-cli.v1","command":"clean","work_dir":".dyn_build","removed":true,"diagnostics":[]}
```
