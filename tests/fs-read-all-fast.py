#!/usr/bin/env python3
"""Chained arenas, bounded contiguous file reads, rollback and FIFO short reads."""
import os,subprocess,tempfile,threading
from pathlib import Path
R=Path(__file__).resolve().parents[1];DYN=str(Path(os.environ.get('DYN',R/'build/dyn-release')).resolve())
SOURCE=r'''use "std/fs"
use "std/mem"
use "std/bytes"
use "std/process"
use "std/errors"
fn require(value: bool, message: []const u8) { if !value { #panic(message) } }
fn main() {
 zero := mem.arena_create(0)
 defer mem.arena_release(zero)
 missing := fs.read_all(zero,"DIR/missing",100)
 require(!missing.ok && missing.kind == errors.Kind.NotFound && mem.arena_used(zero)==0,"missing state")
 none := fs.read_all(zero,"DIR/empty",0)
 require(none.ok && #len(none.value)==0 && mem.arena_used(zero)==0,"zero max empty")
 extra := fs.read_all(zero,"DIR/small",0)
 require(!extra.ok && extra.kind==errors.Kind.Overflow && mem.arena_used(zero)==0,"zero max overflow")
 result := fs.read_all(zero,"DIR/small",6)
 require(result.ok && bytes.equal(result.value,"abcdef"),"lazy read")
 require(mem.arena_mark(zero)==mem.arena_start(zero)+6,"exact mark")
 argv := mem.arena_create(0)
 defer mem.arena_release(argv)
 arguments := process.arguments(argv)
 require(arguments.ok && #len(arguments.value)>0,"lazy arguments")
 prefix := mem.push_array(u8,zero,8)
 for i in 0..8 { prefix[i]=77 }
 mark := mem.arena_mark(zero)
 overflow := fs.read_all(zero,"DIR/large",65537)
 require(!overflow.ok && overflow.kind==errors.Kind.Overflow && mem.arena_mark(zero)==mark,"limit rollback")
 for byte in prefix { require(byte==77,"prefix") }
 large := fs.read_all(zero,"DIR/large",131073)
 require(large.ok && #len(large.value)==131073,"large extent")
 for i in 0..#len(large.value) { require(large.value[i]==#cast(u8,i%251),"large payload") }
 storage: [5 + mem.ArenaBufferOverhead]u8 = []
 fixed := mem.arena_from_buffer(storage[..])
 fixed.data = fixed.data[..mem.ArenaHeader + 5]
 short := fs.read_all(fixed,"DIR/small",100)
 require(!short.ok && short.kind==errors.Kind.Capacity && mem.arena_mark(fixed)== mem.arena_start(fixed),"fixed rollback")
 fixed_empty := mem.arena_from_buffer(storage[..])
 fixed_empty.data = fixed_empty.data[..mem.ArenaHeader]
 empty := fs.read_all(fixed_empty,"DIR/empty",100)
 require(empty.ok && #len(empty.value)==0 && fixed_empty.fixed_buffer && !fixed_empty.owns_memory,"fixed empty")
 full := fs.read_all(fixed_empty,"DIR/small",100)
 require(!full.ok && full.kind==errors.Kind.Capacity && fixed_empty.fixed_buffer && !fixed_empty.owns_memory,"fixed empty capacity")
 bounded := mem.arena_create_bounded(160,160)
 defer mem.arena_release(bounded)
 bounded_small:=fs.read_all(bounded,"DIR/small",100)
 require(bounded_small.ok && bytes.equal(bounded_small.value,"abcdef"),"bounded preferred capacity")
 bounded_mark:=mem.arena_mark(bounded)
 bounded_large:=fs.read_all(bounded,"DIR/large",100)
 require(!bounded_large.ok && bounded_large.kind==errors.Kind.Capacity && mem.arena_mark(bounded)==bounded_mark,"bounded rollback")
 require(bytes.equal(bounded_small.value,"abcdef"),"bounded retained payload")
 chained := mem.arena_create(160)
 defer mem.arena_release(chained)
 first := mem.push_bytes_uninit(chained,16)
 for *byte in first { byte.*=71 }
 forced := mem.push_bytes_uninit(chained,17)
 for *byte in forced { byte.*=82 }
 require(mem.arena_snapshot(chained).blocks==2,"prior forced chain")
 chain_mark:=mem.arena_mark(chained)
 chain_blocks:=mem.arena_snapshot(chained).blocks
 chain_empty:=fs.read_all(chained,"DIR/empty",100)
 require(chain_empty.ok && #len(chain_empty.value)==0 && mem.arena_mark(chained)==chain_mark,"chain empty")
 chain_overflow:=fs.read_all(chained,"DIR/large",65537)
 require(!chain_overflow.ok && chain_overflow.kind==errors.Kind.Overflow && mem.arena_mark(chained)==chain_mark && mem.arena_snapshot(chained).blocks==chain_blocks,"chain rollback")
 directory_error:=fs.read_all(chained,"DIR",100)
 require(!directory_error.ok && mem.arena_mark(chained)==chain_mark && mem.arena_snapshot(chained).blocks==chain_blocks,"I/O error rollback")
 chain_small:=fs.read_all(chained,"DIR/small",6)
 require(chain_small.ok && bytes.equal(chain_small.value,"abcdef"),"chain small payload")
 chain_large:=fs.read_all(chained,"DIR/large",131073)
 require(chain_large.ok && #len(chain_large.value)==131073,"chain large extent")
 for i in 0..#len(chain_large.value) { require(chain_large.value[i]==#cast(u8,i%251),"chain large payload") }
 // Another block must not move earlier output or overwrite independent data.
 tail:=mem.push_bytes_uninit(chained,4096)
 for *byte in tail { byte.*=99 }
 require(bytes.equal(chain_small.value,"abcdef"),"chain output lifetime")
 for byte in first { require(byte==71,"first block canary") }
 for byte in forced { require(byte==82,"prior block canary") }
 fifo_arena:=mem.arena_create(160)
 defer mem.arena_release(fifo_arena)
 fifo_prefix:=mem.push_bytes_uninit(fifo_arena,16)
 for *byte in fifo_prefix { byte.*=83 }
 _=mem.push_bytes_uninit(fifo_arena,17)
 pipe := fs.read_all(fifo_arena,"DIR/pipe",70003)
 require(pipe.ok && #len(pipe.value)==70003,"FIFO short reads")
 for i in 0..#len(pipe.value) { require(pipe.value[i]==#cast(u8,i%239),"FIFO payload") }
 _=mem.push_bytes_uninit(fifo_arena,4096)
 for i in 0..#len(pipe.value) { require(pipe.value[i]==#cast(u8,i%239),"FIFO output lifetime") }
 for byte in fifo_prefix { require(byte==83,"FIFO prefix canary") }
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
