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
| `arena_push`, `mem.push` | caller arena | constant-time bookkeeping in the current block plus zeroing proportional to bytes; growth adds a backing block and may require OS reservation/commitment/page faults; panics when exhausted |
| `arena_push_uninit` | caller arena | constant-time bookkeeping in the current block without zeroing; growth may add a block and require OS reservation/commitment/page faults |
| `arena_create` / `arena_create_bounded` | OS backing | reserve and initialize a header in the first block; `arena_create(0)` selects the target default; Wasm obtains backed linear memory |
| `arena_from_buffer` | caller buffer | constant-time header initialization; consumes 144 bytes plus up to 15 bytes of alignment padding |
| arena rewind/reset | none | proportional to blocks released, plus OS release cost; poisoning touches reclaimed bytes in the retained block when enabled |
| arena release | none | walks and releases all blocks; invalidates the arena pointer |
| arena used/capacity/snapshot | none | proportional to the number of backing blocks |
| arena mark/remaining | none | constant time; remaining describes the newest block only |
| `...any` call | caller stack | descriptor/value packing proportional to argument count |
| typed call | none | native call; commonly inlined in release |
| generic call | none | one compiled instance per distinct type argument set |
| `fmt` construction | caller buffer | proportional to produced bytes; no writer dispatch |
| descriptor I/O | none | syscall(s); full writes may retry partial writes/EINTR |
| file/JSON/CLI retained data | caller arena | proportional to retained data |
| `#typeof` | static metadata | constant-time value construction; no operand evaluation |

A thread's first protected call (a call in a function with `defer`) takes a slot
from runtime-owned pages. The first such call in a program reserves one block of
64 slots (about 264 KiB of address space; only touched pages use memory). Slots
are reused when threads finish, and further blocks are added past 64 concurrent
threads. Programs without cleanup frames reserve nothing. Bare-metal targets use
one fixed slot instead. Debug tracing uses the same scheme.

Release omits diagnostic function tracing. It does not disable overflow, shift, bounds, nil, or
alignment correctness checks. Benchmark matched algorithms, ownership, and I/O strategies before
attributing a difference to the language.

