# Intrusive containers

The unreleased std replaces container types with plain slices and structs that
you declare. Std functions walk fields on your struct by name.

## mem.append

```dyn
// Before
items: []u64
count: usize
_ = mem.append(&items, &count, &arena, value)
for item in items[..count] { use(item) }

// After
items: []u64
_ = mem.append(&arena, &items, value)
for item in items { use(item) }
```

The slice is the whole list, so drop the count. The list must be the newest
allocation on its arena: give it its own arena, or build it completely before
pushing anything else there. A list that grows while other data is pushed on
the same arena becomes a chunk list (`std/container/chunk`).

## string_map

```dyn
// Before
index := maps.Map{}
_ = maps.put(&index, &arena, "name", 42)
found := maps.get(&index, "name")

// After
struct Entry { key: []const u8, hash: u64, hash_next: *Entry, value: usize }
const nil_entry: Entry = Entry{}

table := hash.slots(Entry, &arena, 256)
entry := mem.push(Entry, &arena)
entry.key = strings.clone(&arena, "name")
entry.hash = hash.hash_bytes(seed, entry.key)
entry.value = 42
hash.insert(table, entry)
found := hash.find(table, hash.hash_bytes(seed, "name"), "name", &nil_entry)
```

The slot count is fixed; pick it for the expected size. `find` returns the stub
on a miss. Usually the entry is your own record (a symbol, an asset) with the
three link fields added, not a separate entry type.

## Pool and FreeList

```dyn
// Before
pool := mem.pool_for(Particle, &arena, 256)
spark := mem.acquire(Particle, &pool)
mem.release(&pool, spark)

// After: Particle gains free_next
spark := list.free_pop(&state.first_free, &nil_particle)
if spark == &nil_particle {
  spark = mem.push(Particle, &arena)
} else {
  mem.clear(spark)
}
list.free_push(&state.first_free, spark)
```

## slot_map

The slot array is yours and each slot carries `generation: u32`. `reset` a slot
before use, `retire` it when freed, and use `handle_of` and `resolve`:

```dyn
// Before
table := slots.init_for(Node, &arena, 64)
handle := slots.insert_value(&table, &node)
found := slots.get_value(Node, &table, handle)

// After
nodes := mem.push_array(Node, &arena, 64)
slot := &nodes[0]
slots.reset(slot)
handle := slots.handle_of(nodes, slot)
found := slots.resolve(nodes, handle, &nil_node) // &nil_node once retired
```
