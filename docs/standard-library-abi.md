# Standard-library ABI

The bootstrap SDK keeps standard-library modules as ordinary Dyn source. `use "std/name"`
resolves from the SDK beside the compiler executable, independent of the caller's working
directory. The development tree uses `compiler/std`; an installed SDK uses `std` beside its
`bin` directory. Applications do not need libc or another runtime installation.

Public standard-library functions use the same native ABI as Dyn functions:

- integers and floats use their LLVM scalar representation;
- pointers are thin native pointers;
- slices and strings are `{data: pointer, len: usize}` values passed by value;
- fixed arrays, structs, and enums use compiler-calculated aggregate layouts;
- `bool` uses LLVM `i1` internally;
- no hidden allocator, error channel, or destructor parameter is passed.

C-compatible struct signatures share the target ABI lowering used for foreign
calls, callbacks, and indirect calls. Dyn-only values retain a compiler-private
ABI. Rebuild every Dyn object/library when upgrading this development compiler;
do not mix old aggregate signatures with the new lowering. See [compatibility](stability.md).

`std/c` selects target scalar widths. Struct storage still requires binding-specific
size/alignment/field-offset tests. Payload enums, slices, strings, `any` and native
Dyn variadic packs are not C types. Raw function casts do not validate signatures.
Foreign pointers never imply ownership. See [FFI](ffi.md).

Native variadic calls append hidden borrowed `{descriptor pointer, count}` parameters. The compiler
exposes these directly through the function's named variadic slice. Argument values live in the
caller stack frame. No heap allocation occurs; retaining the pack or its values past the call is invalid.

Foreign C variadic calls use target C ABI varargs. Small integers promote to `i32`; `f32` promotes
to `f64`. Dyn slices, strings, structs, enums, and bools are rejected as variadic arguments.

String literals are immutable UTF-8 byte arrays without a trailing zero. Their slice length is
the byte count. The compiler emits storage only for literals actually used by the program.

The initial Linux x86-64 OS boundary is `#syscall`, backed by `dyn_syscall6`. `std/terminal`
and `write_error` call Linux `write` for file descriptors 1 and 2. Variadic `print`, `println`, and
`eprint` are ordinary procedural Dyn functions. Integer, float, bool, and string
formatting uses stack scratch storage. Float output defaults to six fractional digits with trailing
zeros removed and uses scientific notation outside the ordinary fixed range. `write_char` makes the
otherwise numeric `u8`/character intent explicit. `fmt.Buffer` formats into caller-provided storage.

Fixed-buffer arenas and free lists borrow caller-provided slices. They perform no hidden allocation.
Descriptor reads retry interruption. Descriptor writes retry interruption and partial writes until
complete or failed. Monotonic time is an ordinary `#syscall` wrapper. See `runtime-and-stdlib.md` for
ownership, invalidation, and currently unsupported platform surfaces.

Owned and growing arenas use explicit target-specific mappings. OS allocation returns a thin pointer which is
converted into a slice only through explicit pointer-range syntax with a required end bound.

Core runtime symbols currently reserved for generated code are:

- `_start`
- `dyn_panic`
- `dyn_unwind_set`, `dyn_unwind_link`, `dyn_unwind_unlink`, `dyn_unwind_continue`
- `dyn_syscall6`
- `__dyn_init_*`

These symbols are not source-level standard-library APIs.

## Binding conformance probes

`python3 tests/native-abi.py` compares SDL Event, AudioSpec, FColor and public GPU
create-info layouts (size, alignment and every mapped field offset) with native
headers, and calls a Dyn audio callback through an SDL C callback declaration.
It also checks Linux statx offsets used by `std/fs` and Vulkan loader pointer
sizes when Vulkan headers are available. These checks require no GPU.

The September 2026 local run passed with SDL 3.4.16. The Vulkan 1.4.357 loader was
available; matching upstream Vulkan-Headers v1.4.357 were fetched into build
storage for the layout check. That check passed with `CPATH` pointing at the
downloaded include directory. Header-source URL and archive hash are recorded
in `docs/audit/native-headers-2026-09-21.json`. SDL native handles remain opaque pointers and do not acquire ownership
through assignment. No untested C aggregate ABI is implied by these probes.

The zstd streaming adapter uses static-context and scalar-argument streaming
functions from the provider's advanced API, checked against local zstd 1.5.7
headers and exercised with multi-megabyte reference streams. Workspace comes
from caller storage; the provider does not allocate/free it. These advanced
symbols require a matching provider build and are not a promise of stable ABI
across arbitrary zstd versions.
