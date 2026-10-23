# Arena producers

Every std function that produces data of input-dependent size takes the arena
first and returns the result in it. Caller-buffer forms and size companions
are gone.

```dyn
// Before
digits: [20]u8 = []
text := fmt.u64_decimal(digits[..], count)
copied := strings.clone_into(buffer[..], name)
encoded := base64.encode(output[..], bytes)

// After
text := fmt.u64_decimal(&arena, count)
copied := strings.clone(&arena, name)
encoded := base64.encode(&arena, bytes)
```

To keep a result in fixed storage, wrap the storage:

```dyn
digits: [20]u8 = []
scratch := mem.arena_from_buffer(digits[..])
text := fmt.u64_decimal(&scratch, count)
```

Decoders return `{value, ok}`: `ok` is false only for invalid input. Running
out of arena panics, like any push. Results that are fixed-size (hashes, keys,
`binary.store_*`, `utf8.encode`) and streaming reads (`io.read`, sockets,
`bufio`) still take caller buffers.

`c.string_from_arena(arena, text)` is now `c.string_from_bytes(arena, text)`.
`deflate.inflate(arena, input)` returns `{value, consumed, ok}`; streaming
decompression keeps `deflate.resume` with caller buffers.
