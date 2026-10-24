# Experimental read-only JSON

`std/encoding/json/read` provides a compact, read-only DOM alongside the mutable
`std/encoding/json` module. It uses contiguous 16-byte values and owns a copy of
the input in the caller's arena. This is an experimental API, not a replacement
for the existing mutable tree, constructors, or writer.

```dyn
use "std/encoding/json/read" json
use "std/mem"

fn main() {
  arena := mem.arena_create(mem.MiB)
  defer mem.arena_release(&arena)
  parsed := json.parse(&arena, "{\"count\":12}")
  if !parsed.ok {
    return
  }
  count := json.as_u64(json.get(parsed.root, "count"))
  _ = count
}
```

`parse` returns `{root, ok, kind, error, offset, detail}`. Library errors have
native `error` zero; check `ok` and portable `kind`. A failed parse returns
`&json.nil_value` and rewinds its allocations. Arena exhaustion panics.
`offset` is the parser cursor; errors within strings may identify the beginning
of the string's contents rather than the exact offending escape byte.

Use `kind`, `length`, `get`, `at`, `as_text`, `as_bool`, `as_u64`, `as_i64`, and
`as_f64` to inspect a value. Missing members and out-of-range array positions
return the missing stub, distinct from JSON null. Nil and zero-initialized values
are safe missing values. The conversion helpers return zero or an empty slice
for an incompatible kind; integer conversions also return zero for a fraction
or out-of-range number. Check the kind and application bounds when zero would
be ambiguous.

For linear traversal, create `iterator(container)` and repeatedly call
`next(&iterator)`. Each successful entry contains `value`, borrowed `key`, and
`ok`. Array entries have empty keys; object entries retain input order, including
duplicate keys. `get` returns the first matching duplicate. EOF returns `ok`
false and the missing stub. Repeated indexed traversal with `at` is quadratic.

## Ownership and numeric policy

Every node and decoded string belongs to the arena. Input bytes may change after
a successful parse. Arena rewind, reset, or release invalidates affected nodes,
text, and iterators. Accessors accept only live parser-produced pointers, nil,
or the missing stub. Do not copy or move `Value` records: container children are
located relative to the record's address. Keep `*const Value` views instead.
Create iterators with `iterator()` or zero initialization, and advance them only
through `next`. Copying an iterator copies its position and borrowed document.

Positive integers through `u64::MAX` and negative integers through `i64::MIN`
are retained exactly. Other integers and decimal/exponent forms become binary64,
with its rounding and signed-zero behavior. Nonfinite real overflow is rejected
with portable `Overflow` and `NumberOverflow` detail. Original number spelling
and arbitrary-precision integers are not retained. These rules differ from the
mutable parser, which preserves number text. Strict UTF-8 and paired Unicode
surrogates are required; maximum container nesting is 256.

The value buffer grows geometrically within the stable arena. Containers start
with up to 32 slots; scalar roots need one slot. Unused tail storage is reclaimed
after success, but peak storage can exceed the final retained size. Size a fixed
arena for peak requirements, not just the final node count. Invalid overlap with
unused arena storage is rejected before writing.

The [measured experiment](../performance/2026-10-24-compact-json/README.md)
compares this read-only DOM with the existing mutable DOM and yyjson on one host.
It does not establish a general language or parser ranking.

Optimized x86 builds can scan ordinary ASCII string prefixes with bounded SSE2
loads. The private helper retains a scalar implementation for other targets and
tree emission. Escapes, Unicode validation, ownership, and error handling still
use the same decoder. This does not enable general loop auto-vectorization.
