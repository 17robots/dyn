# Pre-freeze language changes

The compiler rejects most old forms, so work through its errors. The cases below
compile but change behavior, so check them by hand.

- Integer `+`, `-`, `*`, `<<` and negation wrap. Use `math.add_overflows` and
  friends where overflow must be noticed.
- `#cast` to an enum no longer checks the value. Validate with
  `enums.from_int` when the number comes from outside.
- `mem.append` panics at the end of its block instead of moving the list. Use
  `mem.append_grow` when moving is fine, or `mem.try_append` for a stub.
- A character literal with no expected type is `u32`.
- Handles are closed at zero. Test `active` or `is_open`, not `descriptor == -1`.
- `process.CaptureOptions`: a zero timeout is infinite. Set `no_wait` for an
  immediate timeout.

| Old | New |
| --- | --- |
| `struct S { n: i32 = 4 }` | Zero as the default, or set the field in the literal |
| `enum E { A = 4 }` | Dense enum plus a translation table |
| `enum E { A i32 }` | Struct with a `kind` field |
| `#wrap(a * b)` | `a * b` |
| `pointer[..count]` | `#slice(pointer, count)` |
| `distinct`, `packed`, `is`, `union` as names | Rename |
| `for i in -3..3` | `for i: i32 in -3..3` |

See `CHANGELOG.md` for the standard library changes.
