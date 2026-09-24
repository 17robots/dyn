# SQLite

`vendor/sqlite` wraps provider-owned database and statement handles. Dyn scratch/output
storage may come from stack buffers or std arenas; SQLite's internal allocations are owned
and released by SQLite. Successful `open` requires `close`. Failed opens own no handle.
A busy/failed close retains database ownership; finalize its statements and retry.

`prepare(database, sql)` compiles the first statement from a borrowed byte slice; no C-string
scratch is required. `consumed` identifies the remaining SQL for scripts. Comment-only or
empty SQL succeeds with `empty=true` and no handle. Embedded NUL is rejected. A successful
nonempty result owns its `Statement`; keep one owning handle slot.

Binding indices start at one. `bind_i64`, `bind_f64`, `bind_null`, `bind_text`, and `bind_blob`
return zero on success. Text must be valid UTF-8 without NUL; blobs accept arbitrary bytes.
Both byte bindings copy input before return, including empty values, so stack buffers may
be reused immediately. Empty text/blob and SQL NULL remain distinct.

`step` returns `Row`, `Done`, or `Failed`. Row and Done both have `ok=true`; positive codes
retain SQLite's native status. After Done/failure, repeated calls do not re-execute SQL.
`reset` is required for reuse, preserves bindings, and can report the previous execution's
error even though the reset completed. `clear_bindings` releases bindings in Ready state.

`column_count` reports the result-column count. `column` uses zero-based indices and requires
Row state. It returns a typed `Column`: Null, Integer, Float, Text or Blob. No implicit type
conversions occur. Numeric values are copied; byte slices borrow the provider until the next
step/reset/finalize. Retain bytes with `strings.clone(arena, value.bytes)` when needed. Columns
outside the valid range or accessed outside Row fail without calling undefined provider APIs.

`finalize(&statement)` always destroys and zeros that statement slot, even when returning an
execution error. Repeating finalization of the same cleared slot succeeds. Do not independently
finalize a copied handle. Destroy all statements before closing their database; never access
statements concurrently without caller synchronization.

Negative wrapper codes are `InvalidArgument`, `Capacity`, and `Overflow`. Positive errors
are SQLite codes; native Row/Done statuses are preserved in `StepResult.code`. Check `ok`
before consuming a prepare/column/step result. `execute` remains the convenience for SQL
without parameters; use bound statements for data values.

See the executable example in `projects/sqlite-example` and lifecycle tests in `tests/sdk-sqlite`.
Provider contracts: [prepare](https://www.sqlite.org/c3ref/prepare.html),
[bindings](https://www.sqlite.org/c3ref/bind_blob.html),
[columns](https://www.sqlite.org/c3ref/column_blob.html),
[finalization](https://www.sqlite.org/c3ref/finalize.html).

`busy_timeout(database, milliseconds)` rejects negative timeouts. `changes` and
`last_insert_rowid` return checked 64-bit results. `begin(database, mode)`, `commit`,
and `rollback` preserve native status codes. A failed commit may leave a transaction
active; inspect `in_transaction` before retrying or rolling back.
