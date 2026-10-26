# Structured IR snapshot v1

`dyn build DIR --emit-ir --target x86_64-linux` writes canonical structural Dyn IR to stdout. `--output FILE` publishes the exact filename atomically. `--shared` permits a module without `main`. Source errors return 1; usage, internal and output errors return 2. Diagnostics never belong to dump stdout.

The snapshot follows semantic checking and structural lowering, before range proofs, reachability pruning, native or Wasm emission, linking and build caches. Semantic constant folding remains part of checking. It is structured Dyn IR, not LLVM IR, SSA or a derived control-flow graph.

The ASCII header is `dyn-ir1`, followed by target metadata, 21 ordered table sections and `end`, each terminated by LF. References are snapshot-local table indices. Names and arbitrary bytes use a decimal byte length and lowercase hexadecimal bytes. Integer values and binary64 floating representations use exactly 16 hexadecimal digits. Unary negation retains its signed-literal marker. The complete record grammar and field order are maintained in [`ir_dump.h`](../../src/ir_dump.h).

Declaration identities normalize generated module names and generic instances. Paths, spans, compiler addresses, allocation capacities and derived optimization facts are excluded. User-authored string bytes and foreign link names remain unchanged. IDs follow deterministic lowering allocation order; v1 does not promise equality for arbitrary independently renumbered graphs. Target selection remains significant.

Changing this encoding incompatibly requires a format version change. Consumers must reject unknown versions rather than guess field meanings. The stage-3 bootstrap oracle compares complete dumps for an explicitly selected target; executable comparisons remain a separate oracle.

`tests/ir-dump.py` covers byte encoding, signed minima, table structure, repeated jobs settings, project and SDK relocation, target selection, atomic file publication, clean stdout on option errors and absence of code-generation artifacts. Serializer validation occurs before its first write. An output-stream error can leave partial stdout; atomic file publication preserves the old destination on failure.
