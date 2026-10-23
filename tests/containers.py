#!/usr/bin/env python3
"""Intrusive containers: list, hash, chunk and slot_map helpers, mem.append, and SipHash-1-3."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT / 'build/dyn-release')).resolve())
M=(1<<64)-1
def rotl(x,b): return ((x<<b)|(x>>(64-b)))&M
def sip13(k0,k1,m):
    v0=k0^0x736f6d6570736575; v1=k1^0x646f72616e646f6d; v2=k0^0x6c7967656e657261; v3=k1^0x7465646279746573
    def rnd():
        nonlocal v0,v1,v2,v3
        v0=(v0+v1)&M; v1=rotl(v1,13)^v0; v0=rotl(v0,32)
        v2=(v2+v3)&M; v3=rotl(v3,16)^v2
        v0=(v0+v3)&M; v3=rotl(v3,21)^v0
        v2=(v2+v1)&M; v1=rotl(v1,17)^v2; v2=rotl(v2,32)
    n=len(m); full=n-n%8
    for i in range(0,full,8):
        w=int.from_bytes(m[i:i+8],'little'); v3^=w; rnd(); v0^=w
    last=((n&0xff)<<56)|int.from_bytes(m[full:],'little')
    v3^=last; rnd(); v0^=last; v2^=0xff; rnd(); rnd(); rnd()
    return v0^v1^v2^v3


def hash_bytes(seed, key):
    return sip13(seed, seed ^ 0x9e3779b97f4a7c15, key)


# Published SipHash-1-3 vector: key 00..0f, empty message.
assert sip13(0x0706050403020100, 0x0f0e0d0c0b0a0908, b'') == 0xabac0158050fc4dc
CONTAINERS = 'use "std/mem" mem\nuse "std/container/list" list\nuse "std/container/hash" hash\nuse "std/container/chunk" chunk\nuse "std/container/slot_map" slots\n\nstruct Entity {\n  generation: u32,\n  key: []const u8,\n  hash: u64,\n  hash_next: *Entity,\n  parent: *Entity,\n  first: *Entity,\n  last: *Entity,\n  next: *Entity,\n  prev: *Entity,\n  free_next: *Entity,\n  hp: i32,\n}\nstruct EntityChunk { next: *EntityChunk, count: usize, items: [3]Entity }\nstruct EntityList { first: *EntityChunk, last: *EntityChunk, total: usize }\n\nconst nil_entity: Entity = Entity{}\n\nfn main() {\n  arena: mem.Arena\n  entities := mem.push_array(Entity, &arena, 8)\n  first_free: *Entity\n  for i in 0..8 {\n    list.free_push(&first_free, &entities[7 - i])\n  }\n  table := hash.slots(Entity, &arena, 4)\n  root := list.free_pop(&first_free, &nil_entity)\n  slots.reset(root)\n  names: [3][]const u8 = ["a", "boss", "c"]\n  for name in names {\n    e := list.free_pop(&first_free, &nil_entity)\n    slots.reset(e)\n    e.key = name\n    e.hash = hash.hash_bytes(7, name)\n    hash.insert(table, e)\n    list.tree_push_child(root, e)\n  }\n  boss := hash.find(table, hash.hash_bytes(7, "boss"), "boss", &nil_entity)\n  if boss == &nil_entity || boss.key[0] != \'b\' || boss.parent != root || root.first.next != boss {\n    #panic("find")\n  }\n  missing := hash.find(table, hash.hash_bytes(7, "zed"), "zed", &nil_entity)\n  if missing != &nil_entity || missing.hp != 0 {\n    #panic("miss")\n  }\n  handle := slots.handle_of(entities, boss)\n  if slots.resolve(entities, handle, &nil_entity) != boss {\n    #panic("resolve")\n  }\n  list.tree_remove(boss)\n  _ = hash.remove(table, boss)\n  slots.retire(boss)\n  list.free_push(&first_free, boss)\n  if slots.resolve(entities, handle, &nil_entity) != &nil_entity || root.first.next.key[0] != \'c\' {\n    #panic("stale")\n  }\n  again := list.free_pop(&first_free, &nil_entity)\n  slots.reset(again)\n  if again != boss || slots.resolve(entities, handle, &nil_entity) != &nil_entity || !slots.is_live(again) {\n    #panic("reuse")\n  }\n  if slots.resolve(entities, slots.Handle{}, &nil_entity) != &nil_entity {\n    #panic("zero handle")\n  }\n  shared: mem.Arena\n  chunks: EntityList\n  for i in 0..10 {\n    e := chunk.push(&shared, &chunks, Entity{hp: #cast(i32, i)})\n    _ = mem.push(u8, &shared)\n    e.hp += 1\n  }\n  flat := chunk.to_slice(Entity, &shared, &chunks)\n  if chunks.total != 10 || #len(flat) != 10 || flat[9].hp != 10 || chunk.at(&chunks, 4, &nil_entity).hp != 5 || chunk.at(&chunks, 10, &nil_entity) != &nil_entity {\n    #panic("chunk")\n  }\n  queue_first: *Entity\n  queue_last: *Entity\n  for i in 0..3 {\n    list.sll_queue_push(&queue_first, &queue_last, &entities[i])\n  }\n  if list.sll_queue_pop(&queue_first, &queue_last, &nil_entity) != &entities[0] {\n    #panic("queue")\n  }\n}\n'
KEYS = [b'', b'a', b'boss', b'1234567', b'12345678', b'123456789', bytes(range(40))]
SEEDS = [0, 7, 0xffffffffffffffff]
HASHES = 'use "std/container/hash" hash\nfn main() {\n' + ''.join(
    f'  if hash.hash_bytes({seed}, "{"".join(f"\\x{b:02x}" for b in key)}") != {hash_bytes(seed, key)} {{\n    #panic("hash {seed} {len(key)}")\n  }}\n'
    for seed in SEEDS for key in KEYS) + '}\n'
APPEND = """use "std/mem" mem
fn main() {
  arena: mem.Arena
  items: []u64
  for i in 0..1000 {
    _ = mem.append(&arena, &items, #cast(u64, i))
  }
  first := &items[0]
  mem.append_many(&arena, &items, items[..3])
  if #len(items) != 1003 || items[1001] != 1 || first != &items[0] {
    #panic("append")
  }
  storage: [64]u8 = []
  fixed := mem.arena_from_buffer(storage[..])
  small: []u32
  for i in 0..16 {
    _ = mem.append(&fixed, &small, #cast(u32, i))
  }
  if #len(small) != 16 || small[15] != 15 {
    #panic("fixed")
  }
  if #len(std_args()) > 0 {
    _ = mem.push(u8, &arena)
    _ = mem.append(&arena, &items, 5)
  }
}
fn std_args() []u8 {
  empty: []u8
  return empty
}
"""
FAILURES = {
    'not the newest allocation': 'use "std/mem" mem\nfn main() {\n  arena: mem.Arena\n  items: []u64\n  _ = mem.append(&arena, &items, 1)\n  _ = mem.push(u8, &arena)\n  _ = mem.append(&arena, &items, 2)\n}\n',
    'arena exhausted': 'use "std/mem" mem\nfn main() {\n  storage: [16]u8 = []\n  arena := mem.arena_from_buffer(storage[..])\n  items: []u64\n  for i in 0..3 {\n    _ = mem.append(&arena, &items, #cast(u64, i))\n  }\n}\n',
    'node is not an element': 'use "std/container/slot_map" slots\nstruct S { generation: u32 }\nfn main() {\n  a: [2]S = []\n  b: S\n  _ = slots.handle_of(a[..], &b)\n}\n',
}
with tempfile.TemporaryDirectory(prefix='dyn-containers-') as temporary:
    project = Path(temporary)
    source = project / 'main.dyn'
    output = project / ('program.exe' if os.name == 'nt' else 'program')
    for program in (CONTAINERS, HASHES, APPEND):
        source.write_text(program)
        for release in (False, True):
            subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output),
                            *(['--release'] if release else [])], check=True, timeout=90)
            subprocess.run([str(output)], check=True, timeout=10)
    for message, program in FAILURES.items():
        source.write_text(program)
        subprocess.run([DYN, 'build', str(project), '--no-cache', '--quiet', '--output', str(output)], check=True, timeout=90)
        result = subprocess.run([str(output)], capture_output=True, text=True, timeout=10)
        assert result.returncode != 0 and message in result.stderr, (message, result.stderr)
    source.write_text('use "std/container/list" list\nstruct N { value: i32 }\nfn main() {\n  first: *N\n  n: N\n  list.sll_stack_push(&first, &n)\n}\n')
    result = subprocess.run([DYN, 'check', str(project), '--no-cache'], capture_output=True, text=True, timeout=30)
    assert result.returncode == 1 and "N has no field 'next'" in result.stderr, result.stderr
print('PASS containers: intrusive list, hash, chunk and slot_map; mem.append; SipHash-1-3 matches reference (debug/release)')
