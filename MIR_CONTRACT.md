# MIR Contract

This project treats MIR as a verified backend boundary.

## Structural invariants

- Every `MirFunction` has at least one basic block.
- `entry` references a valid block index.
- Block `id` matches its position in `blocks`.
- Every block has a terminator.
- Branch/goto targets reference valid blocks.

## Value invariants

- Every `MirValueId` is defined exactly once.
- Every operand references a previously defined value.
- `phi` nodes appear before non-`phi` instructions in a block.
- `phi` sources are non-empty and come from real predecessor blocks.
- `phi` source value types are compatible with `phi` type.
- `return` and `branch` use defined values.
- Branch condition values are scalar (`bool` or integer).

## Type invariants

- `MirInstr::Eval` and `MirInstr::Phi` must carry stable value types.
- `Unknown` is allowed only as a compatibility escape hatch and should be reduced over time.

## Diagnostic mapping

- `E5001`: malformed CFG structure.
- `E5002`: backend build/codegen failure.
- `E5003`: MIR value/type/SSA contract violation.
