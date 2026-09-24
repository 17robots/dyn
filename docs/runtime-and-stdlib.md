# Runtime and standard library

The C bootstrap compiler emits runtime checks, global initialization, and calls to
small target-specific runtime bridges. Linux x86-64 has the broadest runtime test
coverage. Linux AArch64, macOS, and Windows also have target-specific runtime
objects; cross-linking is not equivalent to native execution.

The SDK consists of ordinary Dyn modules. Common boundaries are:

- `std/mem`: heap/buffer-backed fixed arenas, growing arenas, child arenas, marks,
  scratch scopes, pools and free lists.
- `std/bytes` and `std/encoding/binary`: byte operations and endian conversions.
- `std/fmt`: formatting into caller buffers, without I/O or hidden allocation.
- `std/io`: borrowed `Reader`/`Writer` callbacks and composable stream operations.
- `std/bufio`: caller-backed buffering, explicit flushing, and bounded line reads.
- `std/terminal`: standard-stream adapters and terminal control/key decoding.
- `std/log`: logging to an explicit writer.
- `std/fs`, `std/path`, and `std/os/linux`: files, lexical paths, and Linux services.
- `std/thread` and `std/sync`: caller-stack threads and synchronization primitives.
- `std/strings`, `std/unicode/utf8`, and `std/flags`: text, Unicode, and argument parsing.

See [packages.md](packages.md) for package paths and [memory.md](memory.md) for
ownership rules. Dyn-owned heap allocation goes through arenas. A caller slice
can instead refer to a stack array; bounded operations do not require an arena.
The C compiler and LSP retain their own checked C allocation/ownership policy.

## Results and lifetimes

`io.Result` carries `transferred`, `error`, and `status` (`Complete`, `End`, or
`Error`). Progress remains meaningful when an error follows a partial transfer.
A nonempty operation returning success without progress is an error to exact-I/O
helpers. Buffered readers preserve bytes returned together with an error.

Domain-specific results retain useful data: files, paths, offsets, parsed values,
or syntax locations. They are not forced into a single untyped result structure.
Callback adapters translate domain errors to `io.Result` at stream boundaries.

`fmt.Buffer` borrows caller storage. Formatting returns failure on insufficient
capacity; transactional operations restore logical length, not necessarily unused
backing bytes. Float formatting has explicit bounded precision, while decimal
parsing uses correctly rounded binary64 conversion independent of locale.

Arena reset/rewind/release invalidates affected allocations. It does not close
files, sockets, threads, dynamic libraries, or provider-owned handles. Borrowed
input views and arena-owned output fields must be distinguished in each retaining
API's contract. Temporary-path generation proposes names; reserve them with
`fs.create_exclusive` before use.

Retained-result lifetimes, arena release and optional arena poisoning are
detailed in [memory contracts](memory.md#borrowed-results-and-scratch-lifetimes).
