# SQLite

`vendor/sqlite` wraps provider-owned database and statement handles. Dyn scratch/output
storage may come from stack buffers or std arenas; SQLite's internal allocations are owned
and released by SQLite. A call that can fail returns `T!io.IoErr`. A SQLite code with no
portable kind stays `System(code)` with SQLite's extended code: `error_text(code)` gives
SQLite's text for it, and `error_message(database)` the connection's own description of
the last failure. Successful `open(name, buffer)` requires `close(database)`. Failed
opens own no handle. A busy/failed close
retains database ownership; finalize its statements and retry.

`prepare(database, sql)` compiles the first statement from a borrowed byte slice; no C-string
scratch is required. `consumed` identifies the remaining SQL for scripts. Comment-only or
empty SQL succeeds with `empty=true` and no handle. Embedded NUL is rejected. A successful
nonempty result owns its `Statement`; keep one owning handle slot.

Binding indices start at one. `bind_i64`, `bind_f64`, `bind_null`, `bind_text`, and `bind_blob`
return `!io.IoErr`. Text must be valid UTF-8 without NUL; blobs accept arbitrary bytes.
Both byte bindings copy input before return, including empty values, so stack buffers may
be reused immediately. Empty text/blob and SQL NULL remain distinct.

`step` returns `Row` or `Done`, or fails and leaves the statement `Failed`.
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

Failure kinds follow SQLite's code: mismatch, misuse and range are `InvalidInput`;
busy and locked are `WouldBlock`; full, too-big and out-of-memory are `Capacity`;
permission, auth and read-only are `PermissionDenied`; cannot-open is `NotFound`; the
rest, constraint among them, are `System` with SQLite's code. Wrapper failures are an
invalid argument (`InvalidInput`) and text past the buffer or SQLite's limits (`Capacity`). `execute` remains the convenience for SQL
without parameters; use bound statements for data values.

`tests/vendor-packages.py` exercises the binding when SQLite development files are installed.
Provider contracts: [prepare](https://www.sqlite.org/c3ref/prepare.html),
[bindings](https://www.sqlite.org/c3ref/bind_blob.html),
[columns](https://www.sqlite.org/c3ref/column_blob.html),
[finalization](https://www.sqlite.org/c3ref/finalize.html).

## Helpers

The usual statement life in one call each. Each gives the statement back ready
for its next use, also when it fails.

| Call | Does |
|---|---|
| `run(statement, values...)` | binds, steps to Done, resets and clears bindings |
| `first(statement, values...)` | binds and steps once; true at a row, read it, then `done` |
| `query(statement, values...)`, `next(statement)` | bind, then step row by row: `for try sqlite.next(statement) { ... }` |
| `integer`, `bytes`, `text(arena, ...)` | read a column; `bytes` borrows until the next step, `text` copies |
| `constraint(err)` | the failure is a constraint (duplicate key, foreign key) |
| `cache(database)`, `cached(&cache, sql)`, `cache_close(&cache)` | prepare each SQL text once per connection, up to `CacheSize` (64) |

`open_schema(path, schema)` opens a connection for one thread (no
SQLite mutex, 5 second busy timeout) and runs each schema statement.
`transaction(database, rows, write)` calls `write` for each row inside one
IMMEDIATE transaction and commits, or rolls back and fails. To react to one
row's constraint, catch that `run`'s failure in `write`.

`cached` fails when the SQL does not prepare, holds no statement
(InvalidInput), or the cache is full (Capacity). Its SQL must outlive the cache, as a string literal does.
`cache_close` finalizes every statement; close the database after it.

`busy_timeout(database, milliseconds)` rejects negative timeouts. `changes` and
`last_insert_rowid` return 64-bit counts. `begin(database, mode)`, `commit`,
and `rollback` fail like any other call. A failed commit may leave a transaction
active; inspect `in_transaction` before retrying or rolling back.
