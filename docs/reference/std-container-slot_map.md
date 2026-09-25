# std/container/slot_map

[Reference index](README.md)

## Storage and lifetime

Borrows disjoint record, generation and occupancy backing. Handles include backing identity; initialize generation storage to zero once and preserve it thereafter. Views expire on removal/reinitialization. copy_into can retain bytes in disjoint caller storage.

## Failure behavior

Invalid/stale/foreign handles return missing; copy_into reports Missing or Capacity without writing. Saturated generations retire slots. Not a security capability or a lifetime proof.

## Platforms

Target gates are shown with each source below. Ungated code may still call a target-gated dependency. See [support policy](../stability.md) and native-provider requirements in source `#link` directives.

## Examples and tests

- [tests/sdk-layout/main.dyn](../../tests/sdk-layout/main.dyn)
- [tests/sdk-memory-observation/main.dyn](../../tests/sdk-memory-observation/main.dyn)
- [tests/sdk-observe/main.dyn](../../tests/sdk-observe/main.dyn)

Reviewed behavioral fixtures: [tests/sdk-memory-observation/main.dyn](../../tests/sdk-memory-observation/main.dyn)

## Declarations and source contracts

## Source: compiler/std/container/slot_map/slot_map.dyn

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L8)

Initialize generation backing to zero once. Reinitialization advances generations;
never clear/reuse that backing while stale handles exist. Handles belong to one
backing identity. Generation UINT32_MAX retires a slot permanently, avoiding ABA.
Process-local token, not a serialized ID or a security capability. Do not forge fields.
Identity is the generation backing address; keep that backing alive and never zero it again.

```dyn
pub struct Handle { index: usize, generation: u32, identity: *const u32 }
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L10)

Successful data borrows the live slot until remove or init. Copy the bytes to retain them.

```dyn
pub struct Value { data: []u8, ok: bool }
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L12)

```dyn
pub struct SlotMap {
  data: []u8,
  generations: []u32,
  occupied: []u64,
  slot_size: usize,
  length: usize,
}
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L33)

Borrows three disjoint backing regions. Initialize generations to zero only on first use.
Reinitialization expires all values/handles; existing generations must be preserved.
Do not mutate bookkeeping or independently mutate copies. Thread-confined.

```dyn
pub fn init(data: []u8, generations: []u32, occupied_words: []u64, slot_size: usize) SlotMap
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L54)

```dyn
pub fn capacity(state: *const SlotMap) usize
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L55)

```dyn
pub fn length(state: *const SlotMap) usize
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L59)

Copies source bytes; overlap with data is supported. Wrong size/full returns Handle{}.
No allocation. Insertion scans slots; lookup and removal are constant-time apart from copying.

```dyn
pub fn insert(state: *SlotMap, source: []const u8) Handle
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L72)

Rejects stale, empty, out-of-range and foreign-backing handles. Does not dereference handle.identity.
Returned bytes borrow this slot; successful lookup does not extend their lifetime.

```dyn
pub fn get(state: *SlotMap, handle: Handle) Value
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L84)

Invalid handle returns false without changes. Successful removal zeros data and expires views.
Generation saturation permanently retires the slot; generations never wrap.

```dyn
pub fn remove(state: *SlotMap, handle: Handle) bool
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L96)

```dyn
pub enum CopyStatus { Complete, Missing, Capacity }
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L102)

Copies one live slot into caller storage; result no longer borrows the slot when storage is disjoint.
Missing/Capacity leave destination unchanged. Extra destination bytes are untouched.
Overlap with data is supported, but overlapping output still shares the backing lifetime.
Destination must not overlap generation/occupancy metadata. No allocation.

```dyn
pub fn copy_into(state: *SlotMap, handle: Handle, destination: []u8) CopyStatus
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L110)

```dyn
pub struct Snapshot { capacity: usize, live: usize, available: usize, retired: usize }
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L114)

Allocation-free value snapshot, safe to retain after backing expires. O(capacity) scan.
No synchronization: call only while this thread exclusively accesses the map.

```dyn
pub fn snapshot(state: *const SlotMap) Snapshot
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L125)

Validated lookup represents absence and a live view as distinct alternatives.
Present still borrows slot storage until removal/reinitialization.

```dyn
pub enum Lookup { Missing, Present: []u8 }
```

[Source](../../compiler/std/container/slot_map/slot_map.dyn#L126)

```dyn
pub fn lookup(state: *SlotMap, handle: Handle) Lookup
```
