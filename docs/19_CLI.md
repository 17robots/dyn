# Dyn CLI Reference

## Commands

- `dyn check [entry.dyn] [--json]`
- `dyn build [entry.dyn] [-o out] [--emit-obj|--emit-asm] [--work-dir dir] [--json]`
- `dyn run [entry.dyn] [--work-dir dir] [-- arg ...]`
- `dyn clean [--work-dir dir] [--json]`

## Exit Codes

- `0`: success
- `1`: CLI usage error, frontend/build failure, or runtime process failure mode not represented by normal exit
- `run`: if compiled program exits normally, dyn exits with the same program exit code

## Machine-Readable Output

`--json` is supported on `check`, `build`, and `clean`.

Examples:

```json
{"command":"check","entry":"main.dyn","graph_errors":0,"scope_errors":0,"resolve_errors":0,"semantic_errors":0,"can_codegen":true}
```

```json
{"command":"build","entry":"main.dyn","out":"a.out","work_dir":".dyn_build","emit":"exe","ok":true}
```

```json
{"command":"clean","work_dir":".dyn_build","removed":true}
```
