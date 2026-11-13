# Arena-backed collections

| Need | Use | Moves items | Allocates on add |
| --- | --- | --- | --- |
| Bytes or text | `std/bytes/builder` | Yes, when it grows | Only `append_grow` |
| Everyday growing list | `array.Array(T)` (`std/container/array`) | Yes, when it grows | Yes |
| Dense list, stable | `mem.append` | Never | Panics at the block end |
| Dense list, growing | `mem.append_grow` | Yes | Yes |
| Long list with stable items | Chunk list | Never | One chunk at a time |
| Links through your own nodes | Intrusive list or tree | Never | No |
| Lookup by key | `std/container/map` | Yes, when it grows | Yes |
| Lookup through your own nodes | `std/container/hash` | Never | No, only the slots |
| Reusable slots behind stale checks | Generation handles | Never | No |

## Byte/string builder

`std/bytes/builder` is a byte-oriented builder usable for UTF-8 strings without imposing
text validation. `Builder{}` starts empty; `from_buffer(storage)` starts with borrowed
stack or arena storage. It never stores an allocator or obtains heap memory implicitly.

```dyn
use "std/bytes/builder"
use "std/mem"

fn main() {
  storage: [256]u8
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

Most collections are slices and plain structs that you declare, and std supplies
generic functions that work on them. `array.Array(T)`, `chunk.List(T)` and
`map.Map(K, V)` are the generic types. Each job has one
shape:

| Job | Shape |
| --- | --- |
| Fixed list | a slice from `mem.push_array(T, &arena, n)` |
| Growing list | `array.Array(T)` with `array.init` (`std/container/array`) |
| Growing list whose items never move | a slice that owns its arena, grown with `mem.append` |
| Growing list on a shared arena | a chunk list (`std/container/chunk`) |
| Trees, free lists, an item in several lists | intrusive links (`std/container/list`) |
| Lookup by key | `map.Map(K, V)` with `map.init` (`std/container/map`) |
| Lookup through your own nodes | hash slots chained through `hash_next` (`std/container/hash`) |
| References that survive deletion | generation handles (`std/container/slot_map`) |

Lookups that can miss take a stub and return it instead of nil. A stub is a
constant, so reading it is safe and writing through it is a compile error:

```dyn
const nil_entity: Entity = Entity{}
```

## Arrays

`std/container/array` is the everyday growing list. Like a map, it takes its arena
once, and arrays can share one:

```dyn
use "std/container/array"
use "std/mem"

struct Enemy {
  hp: i32,
}

fn main() {
  arena := mem.arena_create(0)
  enemies: array.Array(Enemy)
  array.init(&enemies, arena)
  array.push(&enemies, Enemy{ hp: 10 })
  boss := array.push_ref(&enemies, Enemy{ hp: 300 })
  boss.hp -= 50
  first := array.get(&enemies, 0)
  if first != nil {
    first.hp += 1
  }
  for e in enemies.items {
    _ = e.hp
  }
}
```

- `items` is an ordinary slice: index it, walk it, pass it on.
- `push` adds to the end; `push_ref` also returns the new element. `push_all`
  adds a slice, `pop` removes the last element as a `{value, ok}` result, and
  `clear` empties the array.
- `get` returns nil past the end.
- A full array moves to storage twice the size, so element pointers and copies
  of `items` go stale at the next push. The old storage stays in the arena.

## Growing lists whose items never move

A growing list can also be a slice whose elements are the newest allocation on its own
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
  per list reserves address space cheaply on 64-bit hosts. A list never moves;
  it panics at the end of its block, and `try_append` returns a stub instead. `append_grow` moves the list to a new block, for a list nothing else holds, such as a result built on a caller's arena. Fixed-buffer arenas never
  chain and require header space. Reset invalidates their allocations too.
- Resetting the arena empties the list; set the slice back to empty as well.

## Chunk lists

A chunk list grows on any arena, including one shared with other data. For a
different chunk size, declare your own structs with the same field names:

```dyn
use "std/container/chunk"

fn spawn(arena: *mem.Arena, enemies: *chunk.List(Enemy)) {
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

`std/container/map` is the everyday map. It grows, takes any key type, and needs
no node struct:

```dyn
use "std/container/map"
use "std/mem"

fn main() {
  arena := mem.arena_create(0)
  ages: map.Map([]const u8, i32)
  map.init(&ages, arena)
  map.insert(&ages, "ada", 36)
  age := map.get(&ages, "ada")
  if age != nil {
    age.* += 1
  }
  visits: map.Map([]const u8, u64)
  map.init(&visits, arena)
  map.upsert(&visits, "ada", 0).* += 1
  it := map.walk(&visits)
  for map.next(&it) {
    _ = it.entry.value
  }
}
```

`map.init(&m, arena)` works for keys that are integers, enums, bools, pointers or text
(`[]u8`, `[]const u8`): they hash and compare by value, text by content. Any other key type is a
compile error at that `init`; give `map.init_with(&m, arena, hash, equal)` a pair instead:
`fn(seed: u64, key: K) u64` and `fn(a: K, b: K) bool`.

`get` returns a pointer or nil, and that pointer goes stale at the next `insert`. Text
keys are borrowed. For keys an attacker chooses, use `map.init_seeded(&m, arena, seed)` with a seed from
`std/crypto/random`.

`insert` sets a value. `upsert(&m, key, initial)` returns the value for key, adding
`initial` first when it is absent, so counting takes one lookup. `walk` and `next`
visit every entry, in no useful order, through `it.entry`.

Each entry has a one-byte tag beside its key and value. A lookup reads tags first and
only reads an entry whose tag matches, so large maps touch less memory.

The intrusive table below allocates nothing after its slots and never moves nodes.
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

## Sets and priority queues

There is no set type. A set is a hash table whose nodes hold only `key`, `hash`
and `hash_next`, and membership is a `hash.find` that does not return the stub.

For a priority queue, keep a slice of items and restore order with a binary heap
in the slice: place a new item at the end and swap it with its parent while it
sorts first. To pop, move the last item to the front and swap it with its first
child while it sorts after one. Parents are at `(i - 1) / 2`, children at
`2 * i + 1` and `2 * i + 2`. A short loop of your own keeps the comparison visible
and needs no callback.
