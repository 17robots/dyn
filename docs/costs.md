# Operation cost guide

This table states the language/library cost model, not a cycle guarantee. Optimizers may remove
work only when semantics remain unchanged.

| Operation | Allocation | Expected cost |
|---|---|---|
| scalar/struct assignment | none | value copy; proportional to aggregate size |
| array assignment | none | copy proportional to array byte size |
| slice/string assignment | none | two machine words; underlying data borrowed |
| slice index | none | bounds check plus access unless proven safe |
| pointer dereference | none | nil/alignment checks plus access unless proven safe |
| checked integer arithmetic | none | operation plus failure branch unless proven safe |
| `arena_try_push` | caller arena | constant time; alignment/capacity checks; returned bytes zeroed |
| arena rewind/reset | none | constant time; does not clear old bytes |
| `...any` call | caller stack | descriptor/value packing proportional to argument count |
| typed call | none | native call; commonly inlined in release |
| `fmt` construction | caller buffer | proportional to produced bytes; no writer dispatch |
| descriptor I/O | none | syscall(s); full writes may retry partial writes/EINTR |
| file/JSON/CLI retained data | caller arena | proportional to retained data |
| `#typeof` | static metadata | constant-time value construction; no operand evaluation |

Release omits diagnostic function tracing. It does not disable overflow, shift, bounds, nil, or
alignment correctness checks. Benchmark matched algorithms, ownership, and I/O strategies before
attributing a difference to the language.

