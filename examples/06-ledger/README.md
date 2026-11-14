# 06 · ledger

Totals by category and by month from a CSV file of expenses.

```sh
dyn run examples/06-ledger -- examples/06-ledger/expenses.csv
```

```
category          count      amount
rent                  1      950.00
groceries             5      228.23
...
```

The sample file has two bad rows on purpose; the report names them and
carries on. See [session.txt](session.txt).

## What it teaches

- **Distinct types.** `distinct type Cents = i64` has `i64`'s representation
  but is its own type. Cents add to cents, but never mix with a plain count
  or an `i64` by accident; converting takes `#cast`. Money is whole cents,
  never a float.
- **Parsing by hand.** `parse_cents` splits `"12.50"` at the dot and checks
  each part with `parse.u64_decimal`. Input that is too large is reported,
  not left to overflow.
- **CSV.** `csv.next(&scan, buffer)` copies one field, unquoted, into the
  buffer you give it and says whether it ended the record. Quoted fields
  like `"Pizza, two slices"` and `"Lamp ""reading"" bulb"` just work. Each
  column gets its own stack buffer so a record's fields stay readable together.
- **Map keys must outlive the map.** A field's buffer is overwritten by the
  next row, so `add_to` copies a key into the arena the first time it is seen.
- **Sorting with function values.** A map has no order, so `rows` copies its
  entries into an array. `sort.sort_by(table, larger_amount)` takes the
  comparison as a value of type `fn(Row, Row) bool`; `print_sorted` passes
  either comparison through.
- **Tables.** `fmt.write_padding` and `fmt.write_u64_width` line up columns
  in a `fmt.Buffer`; one `line.failed` check covers every write.

## Exercises

1. Add a column with each category's share of the total, as a percentage.
2. Accept an optional second argument, a month like `2026-10`, and report
   only that month.
3. Use `sort.stable_by` to sort categories by count while keeping equal
   counts in amount order. Why does it need an arena when `sort_by` does not?
