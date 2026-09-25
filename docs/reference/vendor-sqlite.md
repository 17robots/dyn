# vendor/sqlite

[Reference index](README.md)

## Storage and lifetime

Storage and retention details are declaration-specific; read the adjacent source contracts. Arena parameters allocate from the supplied arena; slices/pointers do not transfer ownership by themselves.

## Failure behavior

Failure and rollback details require declaration-level review. Do not infer atomicity, partial-progress behavior, or panic behavior from the function name.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/lsp-completion/main.dyn](../../tests/lsp-completion/main.dyn)
- [tests/sdk-sqlite/main.dyn](../../tests/sdk-sqlite/main.dyn)

Reviewed behavioral fixtures: no package-wide behavioral claim; inspect linked assertions.

## Declarations and source contracts

## Source: compiler/vendor/sqlite/raw_generated.dyn

## Source: compiler/vendor/sqlite/sqlite.dyn

[Source](../../compiler/vendor/sqlite/sqlite.dyn#L4)

```dyn
pub type Database = rawptr
```

[Source](../../compiler/vendor/sqlite/sqlite.dyn#L5)

```dyn
pub struct OpenResult { database: Database, code: i32, ok: bool }
```

[Source](../../compiler/vendor/sqlite/sqlite.dyn#L9)

Provider allocates database. Successful results require close; failures own nothing.

```dyn
pub fn open(name: []const u8, buffer: []u8) OpenResult
```

[Source](../../compiler/vendor/sqlite/sqlite.dyn#L16)

```dyn
pub fn close(database: Database) i32
```

[Source](../../compiler/vendor/sqlite/sqlite.dyn#L19)

SQL is borrowed only for call. SQLite owns returned error; wrapper releases it.

```dyn
pub fn execute(database: Database, sql: []const u8, buffer: []u8) i32
```

[Source](../../compiler/vendor/sqlite/sqlite.dyn#L29)

Returned bytes borrow database and expire at next SQLite call or close.

```dyn
pub fn error_message(database: Database, maximum: usize) []const u8
```

## Source: compiler/vendor/sqlite/statement.dyn

[Source](../../compiler/vendor/sqlite/statement.dyn#L5)

A statement owns its provider handle. Do not copy live statements or access
fields directly. Database must remain open until every statement is finalized.

```dyn
pub enum State { Ready, Row, Done, Failed }
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L6)

```dyn
pub struct Statement { handle: rawptr, state: State, code: i32 }
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L7)

```dyn
pub struct PrepareResult { statement: Statement, consumed: usize, empty: bool, code: i32, ok: bool }
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L8)

```dyn
pub struct StepResult { state: State, code: i32, ok: bool }
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L9)

```dyn
pub enum ColumnKind { Null, Integer, Float, Text, Blob }
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L10)

```dyn
pub struct Column { kind: ColumnKind, integer: i64, real: f64, bytes: []const u8, code: i32, ok: bool }
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L13)

Negative codes are wrapper failures; positive codes are unchanged SQLite codes.

```dyn
pub const InvalidArgument: i32 = -1
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L14)

```dyn
pub const Capacity: i32 = -2
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L15)

```dyn
pub const Overflow: i32 = -3
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L20)

Compiles the first statement, reporting bytes consumed. Call again with the
remaining SQL to process a script. Empty/comment-only input succeeds with empty=true.
SQL is borrowed only during this call and needs no terminating NUL or scratch.

```dyn
pub fn prepare(database: Database, sql: []const u8) PrepareResult
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L37)

Row and Done are successful, distinct outcomes. Repeated calls after Done or
failure do not implicitly re-execute SQL. reset is required before reuse.

```dyn
pub fn step(statement: *Statement) StepResult
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L50)

Always resets execution state, even when reporting the preceding execution's
error. Parameter values survive reset; use clear_bindings to release them.

```dyn
pub fn reset(statement: *Statement) i32
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L59)

Releases ownership and zeros the caller's slot even if SQLite reports a prior
execution error. Finalizing the same slot again succeeds without provider access.

```dyn
pub fn finalize(statement: *Statement) i32
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L67)

```dyn
pub fn clear_bindings(statement: *Statement) i32
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L71)

```dyn
pub fn bind_null(statement: *Statement, index: i32) i32
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L75)

```dyn
pub fn bind_i64(statement: *Statement, index: i32, value: i64) i32
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L79)

```dyn
pub fn bind_f64(statement: *Statement, index: i32, value: f64) i32
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L96)

SQLite copies bindings before return. Text must be valid UTF-8 without NUL;
use blobs for arbitrary bytes. Inputs may be changed immediately after binding.

```dyn
pub fn bind_text(statement: *Statement, index: i32, value: []const u8) i32
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L101)

```dyn
pub fn bind_blob(statement: *Statement, index: i32, value: []const u8) i32
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L103)

```dyn
pub fn column_count(statement: *const Statement) i32
```

[Source](../../compiler/vendor/sqlite/statement.dyn#L110)

Columns are zero-based and available only after Row. No implicit conversions:
kind distinguishes NULL, empty text, empty blob and numeric zero. Returned bytes
borrow SQLite storage until step/reset/finalize; clone them into an arena to retain.

```dyn
pub fn column(statement: *const Statement, index: i32) Column
```

## Source: compiler/vendor/sqlite/transaction.dyn

[Source](../../compiler/vendor/sqlite/transaction.dyn#L1)

```dyn
pub enum TransactionMode { Deferred, Immediate, Exclusive }
```

[Source](../../compiler/vendor/sqlite/transaction.dyn#L2)

```dyn
pub struct IntegerResult { value: i64, code: i32, ok: bool }
```

[Source](../../compiler/vendor/sqlite/transaction.dyn#L4)

Applies to subsequent busy waits on this connection. Zero disables waiting.

```dyn
pub fn busy_timeout(database: Database, milliseconds: i32) i32
```

[Source](../../compiler/vendor/sqlite/transaction.dyn#L8)

```dyn
pub fn changes(database: Database) IntegerResult
```

[Source](../../compiler/vendor/sqlite/transaction.dyn#L12)

```dyn
pub fn last_insert_rowid(database: Database) IntegerResult
```

[Source](../../compiler/vendor/sqlite/transaction.dyn#L18)

Transactions belong to the connection. A failed commit may leave one active;
query in_transaction, retry or roll back before reusing the connection.

```dyn
pub fn in_transaction(database: Database) bool
```

[Source](../../compiler/vendor/sqlite/transaction.dyn#L23)

```dyn
pub fn begin(database: Database, mode: TransactionMode) i32
```

[Source](../../compiler/vendor/sqlite/transaction.dyn#L29)

```dyn
pub fn commit(database: Database) i32
```

[Source](../../compiler/vendor/sqlite/transaction.dyn#L30)

```dyn
pub fn rollback(database: Database) i32
```
