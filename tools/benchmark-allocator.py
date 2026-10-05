"""Local allocation-dispatch experiment; not a language or application benchmark."""
from pathlib import Path
import hashlib,json,os,statistics,subprocess,time
COMPILER=Path(__file__).resolve().parents[1]
ROOT=COMPILER/'build/allocator-benchmark'
DYN=Path(os.environ.get('DYN', COMPILER/'build/dyn-release')).resolve()
ROOT.mkdir(parents=True,exist_ok=True)
common='''use "std/mem"
use "std/time"
use "std/io"
use "./boundary"
fn allocate(context: rawptr, size: usize, alignment: usize, error: *AllocError) rawptr {
  allocation := mem.arena_push_uninit(#cast(*mem.Arena) context, size, alignment)
  if !allocation.ok { error.* = AllocError.Capacity }
  return #cast(rawptr) allocation.memory
}
fn main() {
  backing: [2 * mem.KiB]u8
  arena := mem.arena_from_buffer(backing[..])
  output := #allocator(&arena, &allocate)
  checksum: u64
  started := time.monotonic_now()
  for batch in 0..10000 {
    mem.arena_reset(&arena)
    for i in 0..128 {
      POINTER
      p.* = #cast(u64) (batch + i)
      checksum += p.*
    }
  }
  elapsed := time.elapsed(started, time.monotonic_now())
  _ = io.println(io.stdout(), "{} {} {}", elapsed.value, checksum, mem.arena_used(&arena))
}
'''
variants={'direct':'p := #cast(*u64) mem.arena_push_or_panic(&arena, #sizeof(u64), #alignof(u64))', 'known':'p := #alloc_or_panic(u64, output)', 'boundary':'p := boundary.next(output)'}
report={'compiler_sha256':hashlib.sha256(DYN.read_bytes()).hexdigest(),'allocations_per_run':1280000,'runs_per_variant':7,'results':[]}
for lto in (True,False):
 for name,expression in variants.items():
  module=ROOT/(name+('-lto' if lto else '-no-lto'));module.mkdir(exist_ok=True)
  (module/'boundary').mkdir(exist_ok=True)
  (module/'boundary/main.dyn').write_text('pub fn next(output: Allocator) *u64 { return #alloc_or_panic(u64, output) }\n')
  (module/'main.dyn').write_text(common.replace('POINTER',expression))
  binary=module/'program'
  start=time.perf_counter()
  command=[str(DYN),'build','--release','--no-cache','--output',str(binary),str(module)]
  if not lto: command.insert(3,'--no-lto')
  p=subprocess.run(command,capture_output=True,text=True,timeout=120)
  assert p.returncode==0,p.stderr
  build_seconds=time.perf_counter()-start
  timings=[]
  for repetition in range(8):
   p=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
   assert p.returncode==0,p.stderr
   ns,checksum,used=map(int,p.stdout.split())
   assert checksum==6480640000 and used==1024,(checksum,used)
   if repetition:timings.append(ns)
  report['results'].append({'variant':name,'lto':lto,'median_ns':statistics.median(timings),'min_ns':min(timings),'max_ns':max(timings),'cold_build_seconds':build_seconds,'executable_bytes':binary.stat().st_size,'samples_ns':timings})
(ROOT/'results.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
