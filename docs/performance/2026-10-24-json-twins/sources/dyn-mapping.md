# Snapshot to Dyn twin mapping

Owned artifact: `dyn/main.dyn`; source snapshot: `original-read.dyn`.
No product source changed. No build, execution, or timing performed by this builder.

- Retained `read_append`, `read_skip`, `read_number`, `read_value`, `read_decoded_string`, `hex_value`, `utf8_byte`, `literal`, and `failed_string` control flow and arithmetic.
- Removed navigation APIs: experiment exposes only complete parsing.
- Value remains two u64 fields. Cursor error becomes u64 with original enum ordinals. Parser's `[]Value` occupies the pointer/capacity pair from twin.h.
- Arena becomes the exact twin.h struct. Allocation, rewind, copy, UTF-8 validation, decimal conversion, and ASCII prefix scanning call the common external helpers used by both twins.
- `lab_ascii` receives `source.data + start`, permitting the one-past pointer for an empty remaining slice, instead of indexing `source[start]`.
- Parse wrapper uses explicit out Result, u64 ok/detail, and reports node count and retained arena bytes on success. Failures preserve the constant missing stub, offset/detail and zero used/retained.
- Native std errors.Kind categorization removed from the output because detail already identifies the error and both twins expose the same narrower experiment ABI.
- Arena mark is `arena.offset`. Overlap is the original interval-overlap test expressed directly with integer subtraction: the allocated prefix may alias input, unused arena tail may not. No overlap helper call remains.
- Bounds checks, checked arithmetic, recursive depth checks, exact-integer threshold tests, UTF-8 validation and all malformed-input handling remain. Original explicit `#wrap` operations remain unchanged.
- Internal impossible node-bound/noncontiguous-arena conditions retain the snapshot's panic behavior. Common allocator must guarantee aligned contiguous storage or fail consistently.

This is an algorithm-matched C/Dyn parser experiment derived from Dyn's reader, **not a literal port of all yyjson internals**. The separate C port must be compared function by function and the full resulting DOM/diagnostics/allocation trace checked before timing.
