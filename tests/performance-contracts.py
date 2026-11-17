#!/usr/bin/env python3
"""Independent search oracles, arena retention and release optimization controls."""
import os, random, subprocess, tempfile, platform, shutil
from pathlib import Path
DYN = str(Path(os.environ.get('DYN', './build/dyn-release.exe' if os.name == 'nt' else './build/dyn-release')).resolve())
def run(*args, ok=True, **kwargs):
    p = subprocess.run(list(map(str,args)), capture_output=True, text=True, timeout=90, **kwargs)
    assert (p.returncode == 0) == ok, (args, p.returncode, p.stdout+p.stderr)
    return p
with tempfile.TemporaryDirectory(prefix='dyn-performance-') as directory:
    root = Path(directory); src=root/'src'; src.mkdir()
    body=['use "std/bytes" bytes', 'use "std/bytes/search" search', 'use "std/testing" t',
          '''use "std/mem" mem
use "std/container/hash" hash
use "std/fail"
use "std/io" io
use "std/bufio" bufio
use "std/bytes/builder" builder
struct Sink { calls: usize, used: usize, fail_after: usize, fail: bool, bytes: [64]u8 }
struct Entry { key: []const u8, hash: u64, hash_next: *Entry, bytes: [1]u8, value: usize }
const nil_entry: Entry = Entry{}
fn sink_write(data: rawptr, status: *fail.Status, source: []const u8) usize {
  state := #cast(*Sink, data)
  state.calls += 1
  if state.fail || (state.fail_after > 0 && state.calls > state.fail_after) {
    failure := fail.make(fail.Kind.PermissionDenied, "write", "", "mock")
    failure.native = -13
    fail.set(status, failure)
    return 0
  }
  amount := #len(source)
  if amount > 3 { amount = 3 }
  for i in 0..amount { state.bytes[state.used + i] = source[i] }
  state.used += amount
  return amount
}
fn main() {''']
    randomizer=random.Random(124)
    cases=[(b'', b''),(b'a', b''),(b'', b'a'),(b'aaaaab',b'aaab'),(b'abcabc',b'abc'),(b'a'*1024,b'a'*30+b'b'+b'a'*30)]
    cases += [(bytes(randomizer.randrange(5) for _ in range(randomizer.randrange(50))),
               bytes(randomizer.randrange(5) for _ in range(randomizer.randrange(12)))) for _ in range(180)]
    def position(found, text): return len(text) if found < 0 else found  # a miss is the length
    def literal(data): return '"'+''.join('\\x%02x'%v for v in data)+'"'
    for text, needle in cases:
        body += ['if true {',f'text := {literal(text)}',f'needle := {literal(needle)}',
                 'table: [64]usize','preparing := fail.Status{ on_failure: fail.panic_on_failure }','p := search.prepare(&preparing, needle, table[..])',
                 f't.expect(search.find(p, text) == {position(text.find(needle), text)}, "KMP oracle")',
                 f't.expect(bytes.find(text, needle) == {position(text.find(needle), text)}, "find oracle")',
                 f't.expect(bytes.find_last(text, needle) == {position(text.rfind(needle), text)}, "rfind oracle")','}']
    body += ['''
  sink := Sink{}
  staging: [4]u8
  buffered := bufio.writer(io.Writer{data: #cast(rawptr, &sink), write: sink_write}, staging[..])
  status: fail.Status
  io.write(&status, bufio.writer_adapter(&buffered), "abcdefghijklmnopqrst")
  t.expect(!status.failed && sink.used == 16 && buffered.used == 4, "direct path keeps tail")
  bufio.writer_flush(&status, &buffered)
  t.expect(!status.failed, "flush tail")
  t.expect(bytes.equal(sink.bytes[..sink.used], "abcdefghijklmnopqrst"), "short writes preserve order")
  sink.fail = true
  failing: fail.Status
  io.write(&failing, bufio.writer_adapter(&buffered), "abcdefghijkl")
  t.expect(failing.failed, "direct failure")
  calls := sink.calls
  io.write(&failing, bufio.writer_adapter(&buffered), "z")
  t.expect(sink.calls == calls, "a failed status writes nothing more")
  sink = Sink{fail_after: 1}
  buffered = bufio.writer(io.Writer{data: #cast(rawptr, &sink), write: sink_write}, staging[..])
  partial: fail.Status
  io.write(&partial, bufio.writer_adapter(&buffered), "abcdefghijkl")
  t.expect(partial.failed && sink.used == 3 && buffered.used == 0, "partial direct failure")
  chunk_storage: [8]u8
  text := "abcdefghijklmnopqrst"
  for capacity in 1..9 {
    for size in 0..21 {
      sink = Sink{}
      buffered = bufio.writer(io.Writer{data: #cast(rawptr, &sink), write: sink_write}, chunk_storage[..capacity])
      chunked: fail.Status
      io.write(&chunked, bufio.writer_adapter(&buffered), text[..size])
      expected: usize = 0
      if size > 0 { expected = (size - 1) % capacity + 1 }
      t.expect(!chunked.failed && buffered.used == expected, "buffered tail unchanged")
      bufio.writer_flush(&chunked, &buffered)
      t.expect(bytes.equal(sink.bytes[..sink.used], text[..size]), "all chunk boundaries")
    }
  }
  table: [1]usize = [99]
  short_table: fail.Status
  _ = search.prepare(&short_table, "ab", table[..])
  t.expect(short_table.failed && table[0] == 99, "prepare failure atomic")
  backing: [8192]u8
  arena := mem.arena_from_buffer(backing[..])
  built := builder.from_buffer(backing[..0])
  for i in 0..1000 { builder.append_grow(arena, &built, "x") }
  t.expect(built.length == 1000, "builder growth")
  t.expect(mem.arena_used(arena) == 1024, "last allocation extends without retained old buffers")
  view := builder.bytes(&built)
  builder.append_grow(arena, &built, view)
  t.expect(built.length == 2000 && mem.arena_used(arena) == 2048, "self append in place")
  _ = mem.push(u8, arena)
  previous := &built.storage[0]
  builder.reserve(arena, &built, 4096)
  t.expect(#len(built.storage) == 4096, "interleaved growth")
  t.expect(&built.storage[0] != previous && built.storage[1999] == 'x', "interleaved allocation copied")
  mem.arena_reset(arena)
  names := hash.slots(Entry, arena, 32)
  initial := mem.arena_used(arena)
  entries: [30]Entry
  for i in 0..30 {
    entries[i].bytes[0] = #cast(u8, i)
    entries[i].key = entries[i].bytes[..]
    entries[i].hash = hash.hash_bytes(3, entries[i].key)
    entries[i].value = i
    hash.insert(names, &entries[i])
  }
  t.expect(mem.arena_used(arena) == initial, "insertion does not allocate")
  key: [1]u8
  for i in 0..30 { key[0] = #cast(u8, i)
    found := hash.find(names, hash.hash_bytes(3, key[..]), key[..], &nil_entry)
    t.expect(found.value == i, "values")
    if i % 2 == 0 { t.expect(hash.remove(names, found), "deletion") }
  }
  for i in 0..30 { key[0] = #cast(u8, i)
    found := hash.find(names, hash.hash_bytes(3, key[..]), key[..], &nil_entry)
    t.expect((found == &nil_entry) == (i % 2 == 0), "removed entries miss")
  }
  values: [10]i64 = [10,9,8,7,6,5,4,3,2,1]
  summarizing := fail.Status{ on_failure: fail.panic_on_failure }
  stats := t.summarize(&summarizing, values[..])
  t.expect(stats.minimum == 1 && stats.median == 5 && stats.p90 == 9 && stats.maximum == 10, "samples")
  invalid: [2]i64 = [5,-1]
  negative: fail.Status
  _ = t.summarize(&negative, invalid[..])
  t.expect(negative.failed && invalid[0] == 5, "invalid sample atomic")
}
''']
    (src/'main.dyn').write_text('\n'.join(body))
    # Validate portable helpers on every supported native OS, even on Linux CI.
    # Linux temporary-directory helpers must not leak unavailable fs declarations.
    for target in ('x86_64-linux', 'aarch64-macos', 'x86_64-windows'):
        run(DYN, 'check', src, '--target', target)
    output=root/('program.exe' if os.name == 'nt' else 'program')
    for flags in ([], ['--release'], ['--release','--no-lto'], ['--release','--opt-level','3']):
        run(DYN,'build',src,'--output',output,*flags)
        run(output)
    if platform.system() == 'Linux':
        # Target isolation must preserve the existing Linux temporary helpers.
        (src/'main.dyn').write_text('''use "std/testing" t
use "std/fail"
use "std/fs" fs
use "std/io" io
use "std/mem" mem
fn main() {
  arena := mem.arena_alloc(0)
  creating: fail.Status
  created := t.temporary_directory(arena, &creating, "dyn-performance-contract")
  t.expect(!creating.failed && created.active, "temporary directory")
  frames: [4]fs.RemovalFrame
  scratch: [4096]u8
  removed: fail.Status
  t.remove_temporary(&removed, &created, frames[..], scratch[..])
  t.expect(!removed.failed && !created.active, "remove temporary directory")
}
''')
        for flags in ([], ['--release']):
            run(DYN, 'build', src, '--output', output, *flags)
            run(output)
    # Small fixture exercises cache identities, actual native attributes, and diagnostics.
    (src/'main.dyn').write_text('fn add(x: i64) i64 { return x + 1 }\nfn main() { if add(4) != 5 { #panic("bad") } }\n')
    env=dict(os.environ,DYN_CACHE_DIR=str(root/'cache'))
    def build(*flags): return run(DYN,'build',src,'--release','--output',output,*flags,env=env)
    build(); assert 'cached' in build().stdout
    assert 'cached' not in build('--cpu','native').stdout
    assert 'cached' in build('--cpu','native').stdout
    assert 'cached' not in build('--opt-level','3').stdout
    remarks=build('--opt-remarks')
    assert 'independent O2:' in remarks.stderr and 'scalar folds' in remarks.stderr, remarks.stderr
    for args in (['--cpu','bogus'],['--opt-level','0'],['--sample-profile',root/'missing'],['--cpu','native','--target','wasm32-wasi','--no-link']):
        run(DYN,'build',src,'--release',*args,ok=False)
    run(DYN,'build',src,'--opt-level','3',ok=False)
    if platform.system()=='Linux' and platform.machine()=='x86_64':
        (src/'main.dyn').write_text('use "std/io" io\nfn main() {\n state: u64 = 1729\n for i in 0..1000 {\n state = (state * 48271) % 2147483647\n }\n io.println("{}", state)\n}\n')
        profile=root/'sample.prof'; profile.write_text('main:10000:1\n'+''.join(f' {i}: 1000\n' for i in range(1,7)))
        profiled=build('--sample-profile',profile,'--opt-remarks'); run(output)
        assert 'samples from profile' in profiled.stdout + profiled.stderr, profiled.stdout + profiled.stderr
        build('--sample-profile',profile)
        assert 'cached' in build('--sample-profile',profile).stdout
        profile.write_text('main:200:200\n 1: 200\n')
        assert 'cached' not in build('--sample-profile',profile).stdout
        profile.write_text('invalid profile\n')
        run(DYN,'build',src,'--release','--sample-profile',profile,'--output',output,ok=False,env=env)
        build()  # An empty profile must not share a cache key with no profile.
        profile.write_text('')
        run(DYN,'build',src,'--release','--sample-profile',profile,'--output',output,ok=False,env=env)
print('PASS search oracles, preallocation, statistics, native CPU/cache, remarks and sample PGO')
