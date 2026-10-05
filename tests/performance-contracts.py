#!/usr/bin/env python3
"""Independent search oracles, arena retention and release optimization controls."""
import os, random, subprocess, tempfile, platform, shutil
from pathlib import Path
DYN = str(Path(os.environ.get('DYN', './build/dyn-release.exe' if os.name == 'nt' else './build/dyn-release')).resolve())
def run(*args, ok=True, **kwargs):
    p = subprocess.run(list(map(str,args)), capture_output=True, text=True, timeout=90, **kwargs)
    assert (p.returncode == 0) == ok, p.stdout+p.stderr
    return p
with tempfile.TemporaryDirectory(prefix='dyn-performance-') as directory:
    root = Path(directory); src=root/'src'; src.mkdir()
    body=['use "std/bytes" bytes', 'use "std/bytes/search" search', 'use "std/testing" t',
          '''use "std/mem" mem
use "std/container/string_map" maps
use "std/io" io
use "std/bufio" bufio
use "std/bytes/builder" builder
use "std/errors" errors
struct Sink { calls: usize, used: usize, fail_after: usize, fail: bool, bytes: [64]u8 }
fn sink_write(data: rawptr, source: []const u8) io.Result {
  state := #cast(*Sink) data
  state.calls += 1
  if state.fail || (state.fail_after > 0 && state.calls > state.fail_after) { return io.Result{transferred: 0, status: io.Status.Error, kind: errors.Kind.PermissionDenied, error: -13} }
  amount := #len(source)
  if amount > 3 { amount = 3 }
  for i in 0..amount { state.bytes[state.used + i] = source[i] }
  state.used += amount
  return io.Result{transferred: amount, status: io.Status.Complete}
}
fn main() {''']
    randomizer=random.Random(124)
    cases=[(b'', b''),(b'a', b''),(b'', b'a'),(b'aaaaab',b'aaab'),(b'abcabc',b'abc'),(b'a'*1024,b'a'*30+b'b'+b'a'*30)]
    cases += [(bytes(randomizer.randrange(5) for _ in range(randomizer.randrange(50))),
               bytes(randomizer.randrange(5) for _ in range(randomizer.randrange(12)))) for _ in range(180)]
    def literal(data): return '"'+''.join('\\x%02x'%v for v in data)+'"'
    for text, needle in cases:
        body += ['if true {',f'text := {literal(text)}',f'needle := {literal(needle)}',
                 'table: [64]usize = []','p := search.prepare(needle, table[..])',
                 't.expect(p.ok, "prepare")',
                 f't.expect(search.find(p.pattern, text) == {text.find(needle)}, "KMP oracle")',
                 f't.expect(bytes.find(text, needle) == {text.find(needle)}, "find oracle")',
                 f't.expect(bytes.find_last(text, needle) == {text.rfind(needle)}, "rfind oracle")','}']
    body += ['''
  sink := Sink{}
  staging: [4]u8 = []
  buffered := bufio.writer(io.Writer{data: #cast(rawptr) &sink, write: &sink_write}, staging[..])
  result := io.write_all(bufio.writer_adapter(&buffered), "abcdefghijklmnopqrst")
  t.expect(result.transferred == 20 && sink.used == 16 && buffered.used == 4, "direct path keeps tail")
  t.expect(bufio.writer_flush(&buffered).status == io.Status.Complete, "flush tail")
  t.expect(bytes.equal(sink.bytes[..sink.used], "abcdefghijklmnopqrst"), "short writes preserve order")
  sink.fail = true
  result = io.write_all(bufio.writer_adapter(&buffered), "abcdefghijkl")
  t.expect(result.status == io.Status.Error && result.transferred == 0, "direct failure")
  calls := sink.calls
  _ = io.write_all(bufio.writer_adapter(&buffered), "z")
  t.expect(sink.calls == calls, "sticky direct failure")
  sink = Sink{fail_after: 1}
  buffered = bufio.writer(io.Writer{data: #cast(rawptr) &sink, write: &sink_write}, staging[..])
  result = io.write_all(bufio.writer_adapter(&buffered), "abcdefghijkl")
  t.expect(result.status == io.Status.Error && result.transferred == 3 && sink.used == 3 && buffered.used == 0, "partial direct failure")
  chunk_storage: [8]u8 = []
  text := "abcdefghijklmnopqrst"
  for capacity in 1..9 {
    for size in 0..21 {
      sink = Sink{}
      buffered = bufio.writer(io.Writer{data: #cast(rawptr) &sink, write: &sink_write}, chunk_storage[..capacity])
      result = io.write_all(bufio.writer_adapter(&buffered), text[..size])
      expected: usize = 0
      if size > 0 { expected = (size - 1) % capacity + 1 }
      t.expect(result.transferred == size && buffered.used == expected, "buffered tail unchanged")
      _ = bufio.writer_flush(&buffered)
      t.expect(bytes.equal(sink.bytes[..sink.used], text[..size]), "all chunk boundaries")
    }
  }
  table: [1]usize = [99]
  t.expect(!search.prepare("ab", table[..]).ok && table[0] == 99, "prepare failure atomic")
  backing: [8192]u8 = []
  arena := mem.arena_from_buffer(backing[..])
  built := builder.from_buffer(backing[..0])
  for i in 0..1000 { t.expect(builder.append_grow(&built, &arena, "x") == builder.ErrorKind.None, "builder growth") }
  t.expect(mem.arena_used(&arena) == 1024, "last allocation extends without retained old buffers")
  view := builder.bytes(&built)
  t.expect(builder.append_grow(&built, &arena, view) == builder.ErrorKind.None, "overlapping growth")
  t.expect(built.length == 2000 && mem.arena_used(&arena) == 2048, "self append in place")
  _ = mem.arena_push_or_panic(&arena, 1, 1)
  previous := &built.storage[0]
  t.expect(builder.reserve(&built, &arena, 4096) == builder.ErrorKind.None, "interleaved growth")
  t.expect(&built.storage[0] != previous && built.storage[1999] == 'x', "interleaved allocation copied")
  before_failure := mem.arena_used(&arena)
  t.expect(builder.reserve(&built, &arena, 8192) == builder.ErrorKind.Capacity, "builder exhausted")
  t.expect(mem.arena_used(&arena) == before_failure && built.length == 2000, "builder failure atomic")
  mem.arena_reset(&arena)
  map := maps.Map{}
  t.expect(maps.reserve(&map, &arena, 30) == maps.ErrorKind.None, "reserve")
  initial := mem.arena_used(&arena)
  key: [1]u8 = []
  for i in 0..30 {
    key[0] = #cast(u8) i
    t.expect(maps.put(&map, &arena, key[..], i) == maps.ErrorKind.None, "put")
  }
  t.expect(mem.arena_used(&arena) == initial + 30, "preallocation avoids table growth")
  t.expect(maps.reserve(&map, &arena, 60) == maps.ErrorKind.None, "reserve populated map")
  used := mem.arena_used(&arena)
  empty := mem.arena_from_buffer(backing[..0])
  t.expect(maps.reserve(&map, &empty, 100) == maps.ErrorKind.Capacity, "reserve failure")
  t.expect(maps.reserve(&map, &arena, #cast(usize) -1) == maps.ErrorKind.Overflow, "reserve overflow")
  t.expect(mem.arena_used(&arena) == used && map.length == 30, "reserve atomic")
  for i in 0..30 { key[0] = #cast(u8) i
    t.expect(maps.get(&map, key[..]).value == i, "preserved values")
    if i % 2 == 0 { t.expect(maps.remove(&map, key[..]), "deletion") }
  }
  maps.clear(&map)
  t.expect(map.length == 0 && mem.arena_used(&arena) == used, "clear retains storage")
  for i in 0..30 { key[0] = #cast(u8) i
    t.expect(!maps.get(&map, key[..]).found, "clear removes remaining entries")
  }
  values: [10]i64 = [10,9,8,7,6,5,4,3,2,1]
  stats := t.summarize(values[..])
  t.expect(stats.ok && stats.minimum == 1 && stats.median == 5 && stats.p90 == 9 && stats.maximum == 10, "samples")
  invalid: [2]i64 = [5,-1]
  t.expect(!t.summarize(invalid[..]).ok && invalid[0] == 5, "invalid sample atomic")
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
use "std/fs" fs
fn main() {
  path: [4096]u8 = []
  created := t.temporary_directory(path[..], "dyn-performance-contract")
  t.expect(created.ok && created.directory.active, "temporary directory")
  frames: [4]fs.RemovalFrame = []
  scratch: [4096]u8 = []
  removed := t.remove_temporary(&created.directory, frames[..], scratch[..])
  t.expect(removed.ok && !created.directory.active, "remove temporary directory")
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
    build('--cpu','native','--emit-ir','--no-link')
    ir=Path(str(output)+'.ll').read_text()
    # LLVM 19 on Apple ARM reports no explicit host feature overrides. LLVM
    # prints an empty string attribute as a bare key, without an equals sign.
    assert '"target-cpu"=' in ir and '"target-features"' in ir, ir
    build('--debug-info','--emit-ir','--no-link')
    assert 'noinline' not in Path(str(output)+'.ll').read_text()
    remarks=build('--opt-remarks')
    assert 'inlin' in remarks.stderr.lower(), remarks.stderr
    for args in (['--cpu','bogus'],['--opt-level','0'],['--sample-profile',root/'missing'],['--cpu','native','--target','wasm32-wasi','--no-link']):
        run(DYN,'build',src,'--release',*args,ok=False)
    run(DYN,'build',src,'--opt-level','3',ok=False)
    if platform.system()=='Linux' and platform.machine()=='x86_64' and shutil.which('ld.lld'):
        (src/'main.dyn').write_text('use "std/io" io\nfn main() {\n state: u64 = 1729\n for i in 0..1000 {\n state = (state * 48271) % 2147483647\n }\n _ = io.println(io.stdout(), "{}", state)\n}\n')
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
