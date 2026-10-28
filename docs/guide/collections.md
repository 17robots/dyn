# Arena-backed collections

## Byte/string builder

`std/bytes/builder` is a byte-oriented builder usable for UTF-8 strings without imposing
text validation. `Builder{}` starts empty; `from_buffer(storage)` starts with borrowed
stack or arena storage. It never stores an allocator or obtains heap memory implicitly.

```dyn
use "std/bytes/builder"
use "std/mem"

fn main() {
  storage: [256]u8 = []
  arena := mem.arena_from_buffer(storage[..])
  text := builder.Builder{}
  if builder.append_grow(&text, arena, "hello") != builder.ErrorKind.None {
    #panic("builder size")
  }
  _ = builder.bytes(&text)
}
```

- `append` is bounded and allocation-free, and reports `Capacity` when the storage is full.
  `reserve` reserves exact capacity from an arena; `append_grow` grows geometrically. Both
  panic when the arena runs out, like any arena push, and report only `Overflow`.
- Appending bytes borrowed from the same builder is supported, including during growth.
- A reported failure preserves length, bytes and storage. `clear` retains capacity.
- Reacquire byte views after mutation. Old arena buffers remain allocated; growth cannot
  reclaim them without invalidating other arena allocations. Reset/release the owning arena
  only after all builder uses and borrowed views have ended.
- Do not independently mutate copies of a builder sharing storage. No internal locking.

Dyn has no container types. Collections are slices and plain structs that you
declare, and std supplies generic functions that work on them. Each job has one
shape:

| Job | Shape |
| --- | --- |
| Fixed list | a slice from `mem.push_array(T, &arena, n)` |
| Growing list | a slice that owns its arena, grown with `mem.append` |
| Growing list on a shared arena | a chunk list (`std/container/chunk`) |
| Trees, free lists, an item in several lists | intrusive links (`std/container/list`) |
| Lookup by key | hash slots chained through `hash_next` (`std/container/hash`) |
| References that survive deletion | generation handles (`std/container/slot_map`) |

Lookups that can miss take a stub and return it instead of nil. A stub is a
constant, so reading it is safe and writing through it is a compile error:

```dyn
const nil_entity: Entity = Entity{}
```

## Growing lists

A growing list is a slice whose elements are the newest allocation on its own
arena. `mem.append` pushes the next element directly after the last one, so
nothing is copied and element addresses never change:

```dyn
use "std/mem"

struct Level {
  enemy_arena: mem.Arena,
  enemies: []Enemy,
}

fn spawn(level: *Level) {
  enemy := mem.append(&level.enemy_arena, &level.enemies, Enemy{hp: 10})
  enemy.hp += 1
  for e in level.enemies {
    _ = e.hp
  }
}
```

- `append` returns the new element. `append_many` appends a slice.
- `append` panics when something else was pushed on that arena after the list,
  which means the list does not own its arena. A list can also share an arena
  if it is built completely before anything else is pushed.
- Use `arena := mem.arena_create(0)` for an explicit default arena. One arena
  per list reserves address space cheaply on 64-bit hosts. Lists can move when
  they outgrow a block; reacquire views after append. Fixed-buffer arenas never
  chain and require header space. Reset invalidates their allocations too.
- Resetting the arena empties the list; set the slice back to empty as well.

## Chunk lists

A chunk list grows on any arena, including one shared with other data. You write
two small structs per element type; `chunk` works through their field names:

```dyn
use "std/container/chunk"

struct EnemyChunk { next: *EnemyChunk, count: usize, items: [64]Enemy }
struct EnemyList { first: *EnemyChunk, last: *EnemyChunk, total: usize }

fn spawn(arena: *mem.Arena, enemies: *EnemyList) {
  enemy := chunk.push(arena, enemies, Enemy{hp: 10})
  enemy.hp += 1
  it := enemies.first
  for it != nil {
    for i in 0..it.count {
      it.items[i].hp -= 1
    }
    it = it.next
  }
}
```

- `push` returns the stored element; its address never changes.
- `at(&list, index, &nil_enemy)` walks to one element; `to_slice(T, &arena, &list)`
  copies the whole list into one contiguous slice.

## Intrusive lists and trees

`std/container/list` links nodes through fields on your own struct: `next`,
`prev`, `first`, `last`, `parent` and `free_next`. A struct missing a field the
function needs is a compile error at the call (`Node has no field 'prev'`).

```dyn
use "std/container/list"

struct Node {
  parent: *Node,
  first: *Node,
  last: *Node,
  next: *Node,
  prev: *Node,
  free_next: *Node,
}

const nil_node: Node = Node{}

fn reuse(first_free: **Node, root: *Node, arena: *mem.Arena) *Node {
  node := list.free_pop(first_free, &nil_node)
  if node == &nil_node {
    node = mem.push(Node, arena)
  } else {
    mem.clear(node)
  }
  list.tree_push_child(root, node)
  return node
}
```

- Stacks and queues use `next`: `sll_stack_push/pop`, `sll_queue_push/pop`.
- Doubly linked lists use `next` and `prev`: `dll_push_back`, `dll_push_front`,
  `dll_insert_after`, `dll_remove`.
- Trees add `parent`, `first` and `last`: `tree_push_child`, `tree_remove`.
- Free lists use their own link, `free_next`, so freeing a node cannot corrupt
  another list. Unlink a node before freeing it.

## Hash tables

A table is a slot slice, `[]*T`, and nodes chain through `key`, `hash` and
`hash_next`. Nothing is allocated after the slots:

```dyn
use "std/container/hash"

struct Symbol { key: []const u8, hash: u64, hash_next: *Symbol, kind: u32 }
const nil_symbol: Symbol = Symbol{}

fn define(table: []*Symbol, symbol: *Symbol, seed: u64) {
  symbol.hash = hash.hash_bytes(seed, symbol.key)
  hash.insert(table, symbol)
}

fn lookup(table: []*Symbol, name: []const u8, seed: u64) *Symbol {
  return hash.find(table, hash.hash_bytes(seed, name), name, &nil_symbol)
}
```

- `slots(T, &arena, count)` makes the table. The slot count is fixed; choose it
  for the expected size.
- `hash_bytes(seed, key)` is SipHash-1-3. With a seed the input cannot predict
  (from `std/crypto/random`), keys cannot be built to collide.
- `insert` does not check for an existing key. `remove` returns whether the
  node was in the table.
- Keys of other types use the same `hash` and `hash_next` fields and a
  hand-written loop over the chain.

## Generation handles

`std/container/slot_map` gives references into your slot array that stop
resolving once the slot is freed, even after it is reused. The slot struct
carries `generation: u32`; an odd generation means live:

```dyn
use "std/container/slot_map" slots

struct Enemy { generation: u32, free_next: *Enemy, hp: i32 }
const nil_enemy: Enemy = Enemy{}

fn damage(enemies: []Enemy, target: slots.Handle) {
  enemy := slots.resolve(enemies, target, &nil_enemy)
  if enemy != &nil_enemy {
    enemy.hp -= 10
  }
}
```

- `reset(node)` prepares a fresh or reused slot: it zeroes the other fields and
  marks the slot live. `retire(node)` frees it; outstanding handles then
  resolve to the stub.
- `handle_of(slots, node)` makes a handle; `resolve` returns the slot or the
  stub. A zero `Handle{}` never resolves.
- Handles are process-local; they are not IDs to serialize or a security
  capability.
