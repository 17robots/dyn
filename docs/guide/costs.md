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
| `#wrap` arithmetic | none | modular operations; division and shift-count checks remain |
| `arena_push`, `mem.push` | caller arena | constant-time bookkeeping plus zeroing proportional to bytes; owned backing may need OS commitment/page faults; panics when exhausted |
| `arena_push_uninit` | caller arena | constant-time bookkeeping without zeroing; owned backing may still need OS commitment/page faults |
| first nonzero push to a zero `Arena{}` | OS backing | reservation plus initialization; platform-dependent commitment/page faults; Wasm obtains backed linear memory |
| arena rewind/reset | none | constant-time bookkeeping by default; poisoning touches every reclaimed byte when enabled |
| `...any` call | caller stack | descriptor/value packing proportional to argument count |
| typed call | none | native call; commonly inlined in release |
| generic call | none | one compiled instance per distinct type argument set |
| `fmt` construction | caller buffer | proportional to produced bytes; no writer dispatch |
| descriptor I/O | none | syscall(s); full writes may retry partial writes/EINTR |
| file/JSON/CLI retained data | caller arena | proportional to retained data |
| `#typeof` | static metadata | constant-time value construction; no operand evaluation |

Release omits diagnostic function tracing. It does not disable overflow, shift, bounds, nil, or
alignment correctness checks. Benchmark matched algorithms, ownership, and I/O strategies before
attributing a difference to the language.

