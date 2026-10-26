# Positions, typed reads and returned results

## Positions

`find` functions return `usize`; a miss returns the length of the searched text.

```dyn
// Before
at := strings.find(name, ".")
if at >= 0 { base = name[..#cast(usize, at)] }

// After
at := strings.find(name, ".")
base := name[..at] // the whole name when there is no "."
if at < #len(name) { ... } // only where the miss matters
```

The compiler rejects `x < 0` and `x >= 0` on unsigned values, so leftover
`-1` checks fail to compile instead of silently changing meaning.

## Parsing numbers

```dyn
// Before
port: u64
if !strings.parse_u64(text, &port) { report() }

// After
if !strings.valid(u16, text) { report() }
port := strings.parse(u16, text) // zero on bad input
```

## JSON

```dyn
// Before
hp := json.object_get(item, "hp")
if hp != nil && json.is_number(hp) { value: i64 ... strings.parse_i64(hp.text, &value) }

// After
hp := json.get(i32, item, "hp") // zero when missing or not a number
tags := json.get(*const json.Value, item, "tags") // &json.nil_value when missing
```

`object_get`, `array_get` and a failed `parse` return `&json.nil_value`, never
nil. Code that compared kinds by number must use the names: kind zero is now
`KindMissing`.

## Out parameters

Each of these returns `{value, ok}` instead of filling an argument:

```dyn
// Before
line: []const u8
for strings.scan_line(&scanner, &line) { use(line) }

// After
for {
  line := strings.scan_line(&scanner)
  if !line.ok {
    break
  }
  use(line.value)
}
```

The same shape applies to `bytes.split_next`, `strings.scan_until` and
`scan_field`, `text/scanner.next_line` and `next_field`, `utf8.next`,
`codepoint_count`, `decoded_size`, `time.parse_iso8601`, `terminal.read_state`,
`terminal.raw` and `ring.pop`. `rand.below(&state, limit)` returns the value.
