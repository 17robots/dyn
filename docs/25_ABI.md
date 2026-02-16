# Dyn Backend ABI (Current v1 Baseline)

This documents the current internal ABI contract used by IR validation and object linking.

## Calling convention

- `call_conv`: `stack_i64`
- Generated arithmetic/compare ops use caller-saved scratch registers (`rax`, `rcx`, `rdx`) and avoid clobbering callee-saved `rbx`.

## Function signature model

Each IR function has:
- `ret_type` (current scalar domain)
- `param_type` (homogeneous scalar param type)
- `param_count`

## Validation rules

The ABI validator currently rejects:
- missing symbol (`AbiMissingSymbol`)
- symbol signature conflicts (`AbiSymbolConflict`)
- argument count mismatch (`AbiArgCountMismatch`)
- calling convention mismatch (`AbiCallConvMismatch`)
- parameter type mismatch (`AbiParamTypeMismatch`)

## Notes

- This contract is intentionally minimal for current backend scope.
- Local frame allocation is rounded up to 16-byte granularity in direct asm emission.
- Future ABI expansion should update this document and associated tests in `src/backend_codegen.zig`.
