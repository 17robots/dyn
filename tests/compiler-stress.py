#!/usr/bin/env python3
"""Long loops, nested aggregate temporaries, callbacks and defer; bounded stack."""
import os, resource, subprocess, tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
source='''struct Pair { x: u64, y: u64 }
enum Payload { Value: Pair, Empty }
fn pair(x: u64) Pair { return Pair{ x: x, y: x + 1 } }
fn callback(p: Pair) u64 { return p.x + p.y }
fn apply(f: *fn(Pair) u64, p: Pair) u64 { return f(p) }
fn increment(p: *u64) { p.* += 1 }
fn main() {
 outer: u64 = 0 total: u64 = 0 calls: u64 = 0
 for outer < 250000 {
  inner: u64 = 0
  for inner < 8 {
   defer increment(&calls)
   p := pair(outer + inner)
   case Payload.Value(p) {
    Payload.Value value => { total += apply(&callback, value) },
    _ => { #panic("payload") },
   }
   values: [2]Pair = [pair(inner), pair(outer)]
   for v in values { total += apply(&callback, v) }
   if (inner == 0 || inner == 7) && outer < 250000 { total += 1 }
   inner += 1
  }
  outer += 1
 }
 if total != EXPECTED || calls != 2000000 { #panic("stress checksum") }
}
'''
# Independent arithmetic oracle, including the two edge iterations per outer.
expected=sum(8*(4*o+3)+4*sum(range(8))+2 for o in range(250000))
source=source.replace('EXPECTED',str(expected))
def stack_limit(): resource.setrlimit(resource.RLIMIT_STACK,(1024*1024,1024*1024))
with tempfile.TemporaryDirectory(prefix='dyn-stress-') as tmp:
 p=Path(tmp);(p/'main.dyn').write_text(source)
 for mode in ([],['--release']):
  subprocess.run([DYN,'build',str(p),'--quiet','--no-cache','--output',str(p/'run'),*mode],cwd=ROOT,check=True)
  subprocess.run([str(p/'run')],check=True,timeout=30,preexec_fn=stack_limit)
print('PASS compiler stress: 2M nested iterations, callbacks/aggregates/defer, 1MiB stack, debug/release')
