# Buffer and arena contracts

Caller buffers may be stack arrays or live arena slices. Capacity is always the supplied
slice length, not the size of an underlying allocation. Returned slices borrow the named
storage; no buffer function silently obtains heap memory. Arena operations retain data only
in the supplied arena. Reset, rewind, or release invalidates affected results.

The following interfaces provide checked, explicit outcomes:

| Interface | Capacity / error reporting | Overlap | Failure effects |
| --- | --- | --- | --- |
| `mem.copy` | Panics if destination is too small | Not supported | Check precedes writes |
| `mem.move` | Panics if destination is too small | Supported | Check precedes writes |
| `strings.clone_into` | `Result.error`, exact `required` bytes | Supported | No writes |
| `strings.join_into`, `replace` | `Result.error`, exact `required` for valid input | Output/input byte overlap rejected | No writes |
| `strings.split_into` | `SplitResult.error`, `required` slice entries | Table must be disjoint from input bytes | No table writes |
| Hex/Base32/Base64 encode/decode | `encoding.Result.error`, exact `required` for valid, representable input | Output/input overlap rejected | No writes |
| `c.string_from_bytes` | `StringResult.error`, `required` includes NUL | Supported | No writes |
| `flags.usage`, `completion` | `TextResult.error`, exact `required` bytes | Output/input text overlap rejected | No writes |
| `builder.append`, `append_grow`, `reserve` | Builder `ErrorKind` | Self-append and overlapping bytes supported | Builder, contents, and arena mark preserved |
| Unicode `case_fold`, `normalize` | `Result.error`, complete UTF-8 prefix `written` | Input/output/work overlap rejected | Overlap writes nothing; later failures may modify work/output |
| ZIP `extract` | `ExtractResult.error` | Destination/payload overlap rejected | Preflight writes nothing; decode/CRC failure may modify output |
| TAR `next_stream` | Sticky numeric error, explicit metadata capacity | Header/metadata overlap rejected | Input may be consumed; names expire at next call; metadata is reused |
| XML `namespace_enter` | `ExpandedName.error` | Event name/attributes must be disjoint from context storage | Scope counters roll back; unused slots may change |
| Process `capture` | Error plus captured prefixes, timeout/limit flags | stdout/stderr overlap rejected | Direct child is terminated/reaped on capture failure; prefixes remain |
| I/O `read`, `write`, `read_exact`, `write_all` | Status plus transferred byte count | Adapter-specific | Partial progress may accompany failure |

Input metadata (slice tables, option definitions, builder/map state) must occupy storage
separate from output bytes. Input bytes must remain unchanged throughout a call. The
transactional guarantees above concern reported errors, not forged slices, mutated public
state, or concurrent access. They do not change other modules' documented partial-output
contracts, including compression and authenticated decryption provider failures.

`InvalidInput`, `Capacity`, `Overflow`, and `Overlap` are distinct codec/string failures.
An empty successful result has `ok=true`; never use slice length to infer success. On
failure, codec/string output slices are empty. `required` is zero when input is invalid or
its required length is not representable. Capacity errors include the exact requirement.
Hex/Base32/Base64 decoders validate before writing; this uses two passes and no temporary
allocation. `decoded_size(source, &size)` validates input and leaves `size` unchanged on
failure. `encoded_size(n)` returns zero on overflow and for empty input.

C strings reject embedded NUL instead of silently truncating names/paths. The bounded C
view distinguishes invalid pointers from missing terminators. Callers must still supply a
maximum within readable foreign storage; a bound cannot validate an arbitrary pointer.

`strings.clone`, `join`, and `split` use the corresponding caller-buffer implementation;
failed arena operations preserve the incoming mark. `join_size` reports byte capacity;
`split_count` reports slice-table capacity. Split elements borrow the original source;
only the table is retained in the arena. Empty fields are preserved.

`mem.Allocation.error` distinguishes invalid alignment, capacity, invalid arena state,
overflow, and OS allocation failure. Growing arenas preserve the OS code in `code`.
`arena_try_sub` returns `ArenaResult { arena, error, ok }`, distinguishing valid zero-capacity
children from failures. Scratch candidates must have independent backing storage; selection
rejects the same arena object and any overlapping backing region with the conflict.

Detailed retained-result lifetimes and owner transfer rules are in [memory contracts](memory.md#borrowed-results-and-scratch-lifetimes).

See [SDK storage details](sdk-additions.md#storage-and-failure-contracts) for metadata
bank sizing, namespace capacity bounds, scratch disjointness, and borrowed lifetimes.
