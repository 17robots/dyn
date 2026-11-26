#!/usr/bin/env python3
"""Chained arenas, bounded contiguous file reads, rollback and FIFO short reads."""
import os,subprocess,tempfile,threading
from pathlib import Path
R=Path(__file__).resolve().parents[1];DYN=str(Path(os.environ.get('DYN',R/'build/dyn-release')).resolve())
SOURCE=r'''use "std/fail"
use "std/fs"
use "std/io"
use "std/mem"
use "std/bytes"
use "std/process"
// The bytes read, or why the read failed.
struct Outcome { data: []u8, failed: bool, error: io.IoErr }
fn read_outcome(arena: *mem.Arena, path: []const u8, maximum: usize) Outcome {
  data := fs.read_all(arena, path, maximum) catch err { return Outcome{ failed: true, error: err } }
  return Outcome{ data: data }
}
fn outcome_is(outcome: Outcome, kind: u8) bool {
  if !outcome.failed { return false }
  case outcome.error {
    .NotFound => { return kind == 1 }
    .PermissionDenied => { return kind == 2 }
    .AlreadyExists => { return kind == 3 }
    .InvalidInput => { return kind == 4 }
    .Capacity => { return kind == 5 }
    _ => { return kind == 6 }
  }
}
fn require(value: bool, message: []const u8) { if !value { #panic(message) } }
fn blocks(arena: *const mem.Arena) usize {
 count: usize = 0
 block := arena.current
 for block != nil {
  count += 1
  block = block.previous
 }
 return count
}
fn main() {
 zero := mem.arena_alloc(0)
 defer mem.arena_release(zero)
 missing_file := read_outcome(zero, "DIR/missing", 100)
 missing := missing_file.data
 require(missing_file.failed && outcome_is(missing_file, 1) && mem.arena_used(zero)==0,"missing state")
 none_file := read_outcome(zero, "DIR/empty", 0)
 none := none_file.data
 require(!none_file.failed && none.len==0 && mem.arena_used(zero)==0,"zero max empty")
 extra_file := read_outcome(zero, "DIR/small", 0)
 extra := extra_file.data
 require(extra_file.failed && outcome_is(extra_file, 5) && mem.arena_used(zero)==0,"zero max overflow")
 result_file := read_outcome(zero, "DIR/small", 6)
 result := result_file.data
 require(!result_file.failed && bytes.equal(result,"abcdef"),"lazy read")
 require(mem.arena_mark(zero)==mem.ArenaHeader+6,"exact mark")
 argv := mem.arena_alloc(0)
 defer mem.arena_release(argv)
 arguments := process.arguments(argv) catch { #panic("lazy arguments") }
 require(arguments.len>0,"lazy arguments")
 prefix := mem.push_array<u8>(zero, 8)
 for i in 0..8 { prefix[i]=77 }
 mark := mem.arena_mark(zero)
 overflow_file := read_outcome(zero, "DIR/large", 65537)
 overflow := overflow_file.data
 require(overflow_file.failed && outcome_is(overflow_file, 5) && mem.arena_mark(zero)==mark,"limit rollback")
 for byte in prefix { require(byte==77,"prefix") }
 large_file := read_outcome(zero, "DIR/large", 131073)
 large := large_file.data
 require(!large_file.failed && large.len==131073,"large extent")
 for i in 0..large.len { require(large[i]==#cast(u8,i%251),"large payload") }
 storage: [5 + mem.ArenaBufferOverhead]u8
 fixed_empty := mem.arena_from_buffer(storage[..])
 fixed_empty.data = fixed_empty.data[..mem.ArenaHeader]
 empty_file := read_outcome(fixed_empty, "DIR/empty", 100)
 empty := empty_file.data
 require(!empty_file.failed && empty.len==0 && fixed_empty.fixed_buffer && !fixed_empty.owns_memory,"fixed empty")
 bounded := mem.arena_from_source(mem.pages(160))
 defer mem.arena_release(bounded)
 bounded_small_file := read_outcome(bounded, "DIR/small", 100)
 bounded_small := bounded_small_file.data
 require(!bounded_small_file.failed && bytes.equal(bounded_small,"abcdef"),"bounded preferred capacity")
 chained := mem.arena_alloc(160)
 defer mem.arena_release(chained)
 first := mem.push_bytes(chained,16)
 for *byte in first { byte.*=71 }
 forced := mem.push_bytes(chained,17)
 for *byte in forced { byte.*=82 }
 require(blocks(chained)==2,"prior forced chain")
 chain_mark:=mem.arena_mark(chained)
 chain_blocks:=blocks(chained)
 chain_empty_file := read_outcome(chained, "DIR/empty", 100)
 chain_empty := chain_empty_file.data
 require(!chain_empty_file.failed && chain_empty.len==0 && mem.arena_mark(chained)==chain_mark,"chain empty")
 chain_overflow_file := read_outcome(chained, "DIR/large", 65537)
 chain_overflow := chain_overflow_file.data
 require(chain_overflow_file.failed && outcome_is(chain_overflow_file, 5) && mem.arena_mark(chained)==chain_mark && blocks(chained)==chain_blocks,"chain rollback")
 directory_error_file := read_outcome(chained, "DIR", 100)
 directory_error := directory_error_file.data
 require(directory_error_file.failed && mem.arena_mark(chained)==chain_mark && blocks(chained)==chain_blocks,"I/O error rollback")
 chain_small_file := read_outcome(chained, "DIR/small", 6)
 chain_small := chain_small_file.data
 require(!chain_small_file.failed && bytes.equal(chain_small,"abcdef"),"chain small payload")
 chain_large_file := read_outcome(chained, "DIR/large", 131073)
 chain_large := chain_large_file.data
 require(!chain_large_file.failed && chain_large.len==131073,"chain large extent")
 for i in 0..chain_large.len { require(chain_large[i]==#cast(u8,i%251),"chain large payload") }
 // Another block must not move earlier output or overwrite independent data.
 tail:=mem.push_bytes(chained,4096)
 for *byte in tail { byte.*=99 }
 require(bytes.equal(chain_small,"abcdef"),"chain output lifetime")
 for byte in first { require(byte==71,"first block canary") }
 for byte in forced { require(byte==82,"prior block canary") }
 fifo_arena:=mem.arena_alloc(160)
 defer mem.arena_release(fifo_arena)
 fifo_prefix:=mem.push_bytes(fifo_arena,16)
 for *byte in fifo_prefix { byte.*=83 }
 _=mem.push_bytes(fifo_arena,17)
 pipe_file := read_outcome(fifo_arena, "DIR/pipe", 70003)
 pipe := pipe_file.data
 require(!pipe_file.failed && pipe.len==70003,"FIFO short reads")
 for i in 0..pipe.len { require(pipe[i]==#cast(u8,i%239),"FIFO payload") }
 _=mem.push_bytes(fifo_arena,4096)
 for i in 0..pipe.len { require(pipe[i]==#cast(u8,i%239),"FIFO output lifetime") }
 for byte in fifo_prefix { require(byte==83,"FIFO prefix canary") }
 // Regular files are sized once: no geometric copies stay pinned in the arena.
 sized:=mem.arena_alloc(0)
 defer mem.arena_release(sized)
 sized_large_file := read_outcome(sized, "DIR/large", 1048576)
 sized_large := sized_large_file.data
 require(!sized_large_file.failed && sized_large.len==131073,"sized extent")
 for i in 0..sized_large.len { require(sized_large[i]==#cast(u8,i%251),"sized payload") }
 require(mem.arena_used(sized)==131073,"sized single allocation")
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-read-all-') as tmp:
 p=Path(tmp);(p/'main.dyn').write_text(SOURCE.replace('DIR',str(p)));(p/'empty').write_bytes(b'');(p/'small').write_bytes(b'abcdef');(p/'large').write_bytes(bytes(i%251 for i in range(131073)));os.mkfifo(p/'pipe')
 for mode in ('debug','release'):
  binary=p/mode;subprocess.run([DYN,'build',str(p),'--'+mode,'--no-cache','--quiet','--output',str(binary)],env=dict(os.environ,DYN_SDK=str(R)),check=True,timeout=120)
  failures=[];stop=threading.Event()
  def writer():
   try:
    # O_RDWR avoids a writer stranded in open if the app fails an earlier check.
    fd=os.open(p/'pipe',os.O_RDWR|os.O_NONBLOCK)
    data=bytes(i%239 for i in range(70003));at=0
    import time
    deadline=time.monotonic()+15
    try:
     while at<len(data):
      if stop.is_set():return
      if time.monotonic()>deadline:raise TimeoutError('FIFO reader did not drain')
      try:at+=os.write(fd,data[at:at+997])
      except BlockingIOError:time.sleep(.001)
    finally:os.close(fd)
   except BaseException as e:failures.append(e)
  t=threading.Thread(target=writer,daemon=True);t.start()
  completed=subprocess.run([str(binary)],capture_output=True,timeout=20)
  if completed.returncode:stop.set()
  t.join(timeout=16)
  assert completed.returncode==0,(mode,completed.stdout,completed.stderr)
  assert not t.is_alive() and not failures,failures
  print('PASS file read',mode,': pointer args/read, EOF/max rollback, prior chained prefixes, contiguous 131073-byte file and 70003-byte FIFO lifetimes')
