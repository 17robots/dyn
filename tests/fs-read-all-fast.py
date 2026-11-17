#!/usr/bin/env python3
"""Chained arenas, bounded contiguous file reads, rollback and FIFO short reads."""
import os,subprocess,tempfile,threading
from pathlib import Path
R=Path(__file__).resolve().parents[1];DYN=str(Path(os.environ.get('DYN',R/'build/dyn-release')).resolve())
SOURCE=r'''use "std/fail"
use "std/fs"
use "std/mem"
use "std/bytes"
use "std/process"
use "std/io" errors
fn require(value: bool, message: []const u8) { if !value { #panic(message) } }
fn main() {
 zero := mem.arena_alloc(0)
 defer mem.arena_release(zero)
 missing_file: fail.Status
 missing := fs.read_all(zero, &missing_file, "DIR/missing", 100)
 require(missing_file.failed && missing_file.failure.kind == errors.Kind.NotFound && mem.arena_used(zero)==0,"missing state")
 none_file: fail.Status
 none := fs.read_all(zero, &none_file, "DIR/empty", 0)
 require(!none_file.failed && #len(none)==0 && mem.arena_used(zero)==0,"zero max empty")
 extra_file: fail.Status
 extra := fs.read_all(zero, &extra_file, "DIR/small", 0)
 require(extra_file.failed && extra_file.failure.kind==errors.Kind.Overflow && mem.arena_used(zero)==0,"zero max overflow")
 result_file: fail.Status
 result := fs.read_all(zero, &result_file, "DIR/small", 6)
 require(!result_file.failed && bytes.equal(result,"abcdef"),"lazy read")
 require(mem.arena_mark(zero)==mem.arena_start(zero)+6,"exact mark")
 argv := mem.arena_alloc(0)
 defer mem.arena_release(argv)
 arguments_status: fail.Status
 arguments := process.arguments(argv, &arguments_status)
 require(!arguments_status.failed && #len(arguments)>0,"lazy arguments")
 prefix := mem.push_array(u8,zero,8)
 for i in 0..8 { prefix[i]=77 }
 mark := mem.arena_mark(zero)
 overflow_file: fail.Status
 overflow := fs.read_all(zero, &overflow_file, "DIR/large", 65537)
 require(overflow_file.failed && overflow_file.failure.kind==errors.Kind.Overflow && mem.arena_mark(zero)==mark,"limit rollback")
 for byte in prefix { require(byte==77,"prefix") }
 large_file: fail.Status
 large := fs.read_all(zero, &large_file, "DIR/large", 131073)
 require(!large_file.failed && #len(large)==131073,"large extent")
 for i in 0..#len(large) { require(large[i]==#cast(u8,i%251),"large payload") }
 storage: [5 + mem.ArenaBufferOverhead]u8
 fixed := mem.arena_from_buffer(storage[..])
 fixed.data = fixed.data[..mem.ArenaHeader + 5]
 short_file: fail.Status
 short := fs.read_all(fixed, &short_file, "DIR/small", 100)
 require(short_file.failed && short_file.failure.kind==errors.Kind.Capacity && mem.arena_mark(fixed)== mem.arena_start(fixed),"fixed rollback")
 fixed_empty := mem.arena_from_buffer(storage[..])
 fixed_empty.data = fixed_empty.data[..mem.ArenaHeader]
 empty_file: fail.Status
 empty := fs.read_all(fixed_empty, &empty_file, "DIR/empty", 100)
 require(!empty_file.failed && #len(empty)==0 && fixed_empty.fixed_buffer && !fixed_empty.owns_memory,"fixed empty")
 full_file: fail.Status
 full := fs.read_all(fixed_empty, &full_file, "DIR/small", 100)
 require(full_file.failed && full_file.failure.kind==errors.Kind.Capacity && fixed_empty.fixed_buffer && !fixed_empty.owns_memory,"fixed empty capacity")
 bounded := mem.arena_alloc_bounded(160,160)
 defer mem.arena_release(bounded)
 bounded_small_file: fail.Status
 bounded_small := fs.read_all(bounded, &bounded_small_file, "DIR/small", 100)
 require(!bounded_small_file.failed && bytes.equal(bounded_small,"abcdef"),"bounded preferred capacity")
 bounded_mark:=mem.arena_mark(bounded)
 bounded_large_file: fail.Status
 bounded_large := fs.read_all(bounded, &bounded_large_file, "DIR/large", 100)
 require(bounded_large_file.failed && bounded_large_file.failure.kind==errors.Kind.Capacity && mem.arena_mark(bounded)==bounded_mark,"bounded rollback")
 require(bytes.equal(bounded_small,"abcdef"),"bounded retained payload")
 chained := mem.arena_alloc(160)
 defer mem.arena_release(chained)
 first := mem.push_bytes_uninit(chained,16)
 for *byte in first { byte.*=71 }
 forced := mem.push_bytes_uninit(chained,17)
 for *byte in forced { byte.*=82 }
 require(mem.arena_snapshot(chained).blocks==2,"prior forced chain")
 chain_mark:=mem.arena_mark(chained)
 chain_blocks:=mem.arena_snapshot(chained).blocks
 chain_empty_file: fail.Status
 chain_empty := fs.read_all(chained, &chain_empty_file, "DIR/empty", 100)
 require(!chain_empty_file.failed && #len(chain_empty)==0 && mem.arena_mark(chained)==chain_mark,"chain empty")
 chain_overflow_file: fail.Status
 chain_overflow := fs.read_all(chained, &chain_overflow_file, "DIR/large", 65537)
 require(chain_overflow_file.failed && chain_overflow_file.failure.kind==errors.Kind.Overflow && mem.arena_mark(chained)==chain_mark && mem.arena_snapshot(chained).blocks==chain_blocks,"chain rollback")
 directory_error_file: fail.Status
 directory_error := fs.read_all(chained, &directory_error_file, "DIR", 100)
 require(directory_error_file.failed && mem.arena_mark(chained)==chain_mark && mem.arena_snapshot(chained).blocks==chain_blocks,"I/O error rollback")
 chain_small_file: fail.Status
 chain_small := fs.read_all(chained, &chain_small_file, "DIR/small", 6)
 require(!chain_small_file.failed && bytes.equal(chain_small,"abcdef"),"chain small payload")
 chain_large_file: fail.Status
 chain_large := fs.read_all(chained, &chain_large_file, "DIR/large", 131073)
 require(!chain_large_file.failed && #len(chain_large)==131073,"chain large extent")
 for i in 0..#len(chain_large) { require(chain_large[i]==#cast(u8,i%251),"chain large payload") }
 // Another block must not move earlier output or overwrite independent data.
 tail:=mem.push_bytes_uninit(chained,4096)
 for *byte in tail { byte.*=99 }
 require(bytes.equal(chain_small,"abcdef"),"chain output lifetime")
 for byte in first { require(byte==71,"first block canary") }
 for byte in forced { require(byte==82,"prior block canary") }
 fifo_arena:=mem.arena_alloc(160)
 defer mem.arena_release(fifo_arena)
 fifo_prefix:=mem.push_bytes_uninit(fifo_arena,16)
 for *byte in fifo_prefix { byte.*=83 }
 _=mem.push_bytes_uninit(fifo_arena,17)
 pipe_file: fail.Status
 pipe := fs.read_all(fifo_arena, &pipe_file, "DIR/pipe", 70003)
 require(!pipe_file.failed && #len(pipe)==70003,"FIFO short reads")
 for i in 0..#len(pipe) { require(pipe[i]==#cast(u8,i%239),"FIFO payload") }
 _=mem.push_bytes_uninit(fifo_arena,4096)
 for i in 0..#len(pipe) { require(pipe[i]==#cast(u8,i%239),"FIFO output lifetime") }
 for byte in fifo_prefix { require(byte==83,"FIFO prefix canary") }
 // Regular files are sized once: no geometric copies stay pinned in the arena.
 sized:=mem.arena_alloc(0)
 defer mem.arena_release(sized)
 sized_large_file: fail.Status
 sized_large := fs.read_all(sized, &sized_large_file, "DIR/large", 1048576)
 require(!sized_large_file.failed && #len(sized_large)==131073,"sized extent")
 for i in 0..#len(sized_large) { require(sized_large[i]==#cast(u8,i%251),"sized payload") }
 sized_state:=mem.arena_snapshot(sized)
 require(sized_state.used==131073 && sized_state.peak_used==131073,"sized single allocation")
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
  print('PASS file read',mode,': pointer args/read, EOF/max/capacity rollback, prior chained prefixes, contiguous 131073-byte file and 70003-byte FIFO lifetimes')
