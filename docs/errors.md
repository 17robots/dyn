# Error-value conventions

Dyn deliberately has no universal `Result` syntax or exception channel. Choose the smallest
ordinary value which preserves information the caller needs:

- `bool` for a yes/no operation with no useful failure detail;
- an unambiguous sentinel for lookup-like operations;
- a struct for a value plus orthogonal status, count, or OS error number;
- an enum when callers should exhaustively distinguish several outcomes;
- panic only for broken invariants or an explicitly infallible convenience operation.

The standard library follows these conventions but does not prescribe application architecture.
OS operations commonly return `{value, error, ok}` because partial counts and native error numbers
matter. Parsers commonly return `{value, error_offset, ok}`. Predicates return `bool`.

Ownership remains independent of success. Documentation must say whether returned slices borrow
input, occupy caller storage, or live in a supplied arena. Failure must not silently allocate.

