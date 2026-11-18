# SQLite

`vendor/sqlite` wraps provider-owned database and statement handles. Dyn scratch/output
storage may come from stack buffers or std arenas; SQLite's internal allocations are owned
and released by SQLite. Every call takes a `*fail.Status` first: the first failure sticks,
and later calls given a failed status do nothing. A failure keeps SQLite's code in
`failure.native` and its text in the message. Successful `open(&status, name, buffer)`
requires `close(&status, database)`. Failed opens own no handle. A busy/failed close
retains database ownership; finalize its statements and retry.

`prepare(&status, database, sql)` compiles the first statement from a borrowed byte slice; no C-string
scratch is required. `consumed` identifies the remaining SQL for scripts. Comment-only or
empty SQL succeeds with `empty=true` and no handle. Embedded NUL is rejected. A successful
nonempty result owns its `Statement`; keep one owning handle slot.

Binding indices start at one. `bind_i64`, `bind_f64`, `bind_null`, `bind_text`, and `bind_blob`
take the status and return nothing. Text must be valid UTF-8 without NUL; blobs accept arbitrary bytes.
Both byte bindings copy input before return, including empty values, so stack buffers may
be reused immediately. Empty text/blob and SQL NULL remain distinct.

`step` returns `Row`, `Done`, or `Failed`; Failed also records the failure on the status.
After Done/failure, repeated calls do not re-execute SQL.
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

Failure kinds follow SQLite's code: constraint, mismatch and too-big are `InvalidInput`;
busy and locked are `WouldBlock`; full and out-of-memory are `Capacity`; permission,
auth and read-only are `PermissionDenied`; cannot-open is `NotFound`; misuse is
`InvalidState`; the rest are `System`. Wrapper failures (an invalid argument, text that
does not fit, a length past SQLite's limits) have negative native codes. `execute` remains the convenience for SQL
without parameters; use bound statements for data values.

`tests/vendor-packages.py` exercises the binding when SQLite development files are installed.
Provider contracts: [prepare](https://www.sqlite.org/c3ref/prepare.html),
[bindings](https://www.sqlite.org/c3ref/bind_blob.html),
[columns](https://www.sqlite.org/c3ref/column_blob.html),
[finalization](https://www.sqlite.org/c3ref/finalize.html).

## Helpers

The usual statement life in one call each. Each takes the status and gives the
statement back ready for its next use, so the caller checks the status once.

| Call | Does |
|---|---|
| `run(&status, statement, values...)` | binds, steps to Done, resets and clears bindings |
| `first(&status, statement, values...)` | binds and steps once; true at a row, read it, then `done` |
| `query(&status, statement, values...)`, `next(&status, statement)` | bind, then step row by row |
| `integer`, `bytes`, `text(arena, ...)` | read a column; `bytes` borrows until the next step, `text` copies |
| `constraint(&status.failure)` | the failure is a constraint (duplicate key, foreign key) |
| `cache(database)`, `cached(&status, &cache, sql)`, `cache_close(&cache)` | prepare each SQL text once per connection, up to `CacheSize` (64) |

`open_schema(&status, path, schema)` opens a connection for one thread (no
SQLite mutex, 5 second busy timeout) and runs each schema statement.
`transaction(&status, database, rows, write)` calls `write` for each row inside
one IMMEDIATE transaction and commits, or rolls back and records the failure.
To react to one row's constraint, give that `run` its own status.

`cached` returns nil after a failure: the SQL does not prepare, holds no
statement (InvalidInput), or the cache is full (Capacity). Its SQL must outlive the cache, as a string literal does.
`cache_close` finalizes every statement; close the database after it.

`busy_timeout(&status, database, milliseconds)` rejects negative timeouts. `changes` and
`last_insert_rowid` return 64-bit counts. `begin(&status, database, mode)`, `commit`,
and `rollback` keep SQLite's code in `failure.native`. A failed commit may leave a transaction
active; inspect `in_transaction` before retrying or rolling back.
