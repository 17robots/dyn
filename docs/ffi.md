# Foreign-function interface

The bootstrap compiler supports explicit native declarations:

```dyn
extern fn add "library_add"(left: u64, right: u64) u64
```

The local name participates in Dyn module visibility and qualification. The string is the exact
native linker symbol. It must be non-empty and contain only linker-symbol characters. Duplicate
native symbols in one build are rejected. Parameters and results require concrete types; argument
counts and Dyn-side types are checked at compile time.

`dyn build app --link native.o --link support.a` passes explicit application FFI inputs to the linker.
Packages declare native dependencies directly in Dyn source with `#link("SDL3")`. Importing that
package automatically locates and links the declared native library. Put `#link` in a target-gated
source file when dependencies differ by platform. `DYN_LIBRARY_PATH` adds colon-separated search
directories; an explicit matching `--link` input overrides discovery.
An explicit `.so` input enables the x86-64 Linux dynamic loader. No library search, implicit libc,
automatic ownership conversion is performed. `tools/dyn-bind.py` (`dyn-bind` in an installed SDK)
is a conservative header-text translator (not a complete C preprocessor or Clang AST frontend) generating declarations for representable scalar,
pointer, function-pointer, simple struct/record typedef, function, and variadic declarations.
The translator does not preprocess conditional headers or implement arbitrary C declarators.
Unsupported C constructs are omitted instead of guessed and are listed with reasons at the end of
the generated file. By-value unions, bitfields, anonymous fields, expression/function-like macros,
and functions exposing an unrepresentable type require explicit bindings or a small C adapter.
Pointers to unions are emitted as opaque `rawptr` values. Generated aggregate bindings still need
ABI size/alignment tests against their C library. C variadics use trailing `...`;
small integers and `f32` receive C default promotions. The foreign implementation
must obey the selected platform ABI and Dyn's documented layouts. `std/c` selects LP64 versus
Windows LLP64 scalar aliases through target-gated sources; generated C `long` uses those aliases.
Generated plain `char` uses `c.char`: unsigned on AArch64 Linux, signed on the
other supported targets with their default C compiler settings. Flags such as
`-fsigned-char`/`-funsigned-char` require explicit binding overrides. Explicit
`signed char`/`unsigned char` always map to `i8`/`u8`.
Enum generation requires literal signed 32-bit values and the default C enum ABI
(no `-fshort-enums`). Integer literals support decimal, hex and C octal; unsupported
enum expressions are reported without inventing subsequent values. Pointers carry no ownership
transfer unless the API contract says so. Foreign C-variadic functions may be called through
function pointers; fixed arguments and promoted trailing arguments remain checked.

C-compiler tests cover integer/float C variadics, struct/array storage layouts,
aggregate size/alignment/field offsets,
C-to-Dyn callbacks, nullable pointers, direct foreign mutable storage and storage through an accessor,
raw objects, static archives, and shared objects. Dyn can declare foreign data
symbols with `extern local_name "link_symbol": Type`; such declarations never initialize or own storage.

## Aggregate ABI boundary

C-compatible nonempty structs now use one target ABI lowering path for direct
calls, returns, function pointers, and C-to-Dyn callbacks. This same lowering is
used by native Dyn functions so taking a function address cannot silently change
its convention. Supported targets are SysV x86-64 Linux, Windows x64, and AAPCS64
Linux/macOS. The implementation classifies integer/SSE eightbytes and register
exhaustion on SysV, integer-sized versus indirect records on Windows, and small
records/homogeneous floating aggregates on AArch64. Larger records use indirect
storage and hidden result pointers as required by the target.

Struct fields may contain C scalars, pointers, supported enums, nested structs,
and fixed nonempty arrays. Packed storage must match the C declaration exactly.
Slices, strings, `any`, payload enums, direct array parameters/results, empty
structs and aggregate C varargs are not supported C boundaries. These are rejected
when a foreign function is called or its address is taken. Unsupported C unions,
bitfields, vectors, extended floating types and special calling conventions still
need explicit adapters. Casting an arbitrary raw address does not validate it.

`tests/aggregate-abi.py` checks 16 shapes, register exhaustion, direct/indirect
calls, returns and callbacks against GCC and Clang in debug/release. `--cross`
builds probes for native CI; cross-linking alone is not execution evidence.
Platform rules follow [SysV AMD64](https://gitlab.com/x86-psABIs/x86-64-ABI),
[Microsoft x64](https://learn.microsoft.com/en-us/cpp/build/x64-calling-convention?view=msvc-170),
and [AAPCS64](https://github.com/ARM-software/abi-aa/blob/main/aapcs64/aapcs64.rst).

A foreign function may invoke a Dyn callback that panics. Dyn caller defers run,
but this does not provide C++ exception unwinding or cleanup for intervening C
frames. Foreign resources require an explicit cleanup contract.

## Binding reports and layout verification

```sh
python3 tools/dyn-bind.py api.h -o bindings.dyn --report bindings.json \
  --verify-layout x86_64-linux --cc cc --dyn build/dyn-release --run-layout
```

The JSON report lists known omissions with kind, name, reason and source line.
It explicitly describes the text frontend's incomplete parsing scope: includes,
conditionals, attributes and arbitrary declarators require review. It is not a
complete inventory of every C declaration. Ordinary UTF-8 source string literals
are translated byte-for-byte, including C octal/hex/simple escapes; wide/universal
escapes and out-of-byte-range escapes are reported instead of guessed. Comment
markers inside literals remain data. Nested pointer `const` stays on its original
level. Empty `()` C declarations and callback types are treated as non-prototypes
under the C11 baseline and omitted; write `(void)` for a no-argument prototype. Use a preprocessed, reviewed small
header surface or write an adapter for complex system headers.

Layout verification compiles C `sizeof`, `_Alignof`, and `offsetof` oracle functions
from the actual header, links them against the generated Dyn records, and compares
all generated fields. Supply the target compiler and matching flags with `--cc`,
for example `--cc 'zig cc -target aarch64-linux-musl'`. Without `--run-layout` the
report says `cross-linked-only`; with it, the host must be able to execute the
selected target. A mismatch fails generation and records failure. Verify calls
with a provider integration test too: matching storage alone cannot prove a
function signature or an ownership contract correct.
