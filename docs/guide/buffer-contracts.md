# Buffer and arena contracts

Std has one way to produce data whose size depends on the input: the function
takes `arena: *mem.Arena` first and returns the result in that arena. There are
no caller-buffer duplicates (`_into`) and no size-query companions (`_size`,
`_count`). To produce into fixed storage, wrap it in an arena:

```dyn
storage: [64 + mem.ArenaBufferOverhead]u8 = []
arena := mem.arena_from_buffer(storage[..])
text := fmt.u64_decimal(arena, 42)
```

Running out of arena panics, like every arena push. Producers that cannot know
their output size in advance (JSON encoding, inflate, case folding) write into a
trial block and retry with a bigger one, rewinding between attempts, so the
arena keeps only the final output. A fixed-buffer arena that cannot hold the
output panics.

Caller storage remains at fixed-size, streaming, and raw ABI boundaries:

- Fixed-size results: hashes and keys (`sha2.finish`, `hmac.sha256`,
  `x25519`), `binary.store_*`, `utf8.encode`, socket addresses.
- Raw C ABI scratch: `c.string_into` validates and writes a NUL-terminated
  string into borrowed caller storage without allocation. Vendor adapters use
  this bounded primitive to preserve their existing scratch-buffer capacities;
  ordinary retained C strings use `c.string_from_bytes`.
- Streaming: `io.read`, `fs.read`, socket and TLS reads, `bufio`, CSV and TAR
  stream readers, `deflate.resume`. These fill the caller's buffer and report
  how much they transferred.

Failure of an arena producer pushes nothing: the arena is rewound to where it
was. Input that is not valid (bad UTF-8, a malformed escape, a corrupt stream)
is reported as `ok` false; size never is.

| Producer | Result |
| --- | --- |
| `strings.clone`, `join`, `split`, `replace`, `format` | Slice in arena; `split` elements borrow the source |
| `fmt.u64_decimal`, `i64_decimal`, `f64_decimal`, `u64_base` | Text in arena |
| Hex/Base32/Base64 `encode`, `decode` | Bytes in arena; `decode` returns `{value, ok}` |
| JSON `encode`, `encode_pretty`, `write_string` | Text in arena; empty when the value is not encodable |
| `path.join`, `clean`, `safe_join`, `relative`, `url.percent_encode`, `percent_decode` | Text in arena |
| `c.string_from_bytes` | NUL-terminated copy in arena; embedded NUL is invalid input |
| `deflate.inflate`, `gunzip`, `gzip.decompress`, `zstd.compress`, `decompress`, `zip.extract` | Bytes in arena |
| `png`, `qoi` `encode`, `decode` | Bytes or pixels in arena |
| Unicode `case_fold`, `normalize` | Text in arena; `ok` false for invalid UTF-8 |
| HTTP and WebSocket writers, DNS queries, `time.format_iso8601`, `debug.hexdump`, `flags.usage` | Bytes in arena |
| `process.environment`, `fs.read_link`, `fs.app_directory` | Text in arena |

`mem.arena_try_push` reports exhaustion through `Allocation.error`, which distinguishes invalid
alignment, capacity, invalid arena state and overflow. Mapping-allocation failures
keep their native code, including zero. Header commitment currently reports the
synthetic out-of-memory code `-12`; it does not expose the underlying Win32
commitment diagnostic. Ordinary page-commit failures during a push still panic.

Retained-result lifetimes are listed in [memory](memory.md#what-each-result-borrows).
A numeric mark is not a generation-checked token: do not reuse marks across
reset or release, or with another arena.
