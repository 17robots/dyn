#!/usr/bin/env python3
"""Clock failure propagation through std consumers; Linux x86-64 seccomp only."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
SOURCE = '''use "std/time" time
use "std/profile" profile
use "std/testing" testing
use "std/net" net
use "std/net/dns" dns
use "std/process" process
use "std/mem" mem
use "std/errors" errors
struct Filter { code: u16, jt: u8, jf: u8, k: u32 }
struct Program { length: u16, filter: *Filter }
fn require(ok: bool) { if !ok { #panic("clock consumer failure propagation") } }
fn main() {
  span := profile.begin("clock")
  synthetic := testing.Benchmark{started:time.ClockResult{kind:errors.Kind.System}, iterations:0}
  synthetic_each := testing.benchmark_nanoseconds_each(&synthetic)
  require(!synthetic_each.ok && synthetic_each.error == 0 && synthetic_each.kind == errors.Kind.System)
  synthetic.started = time.ClockResult{ok:true}
  synthetic_replay := testing.benchmark_nanoseconds_each(&synthetic)
  require(!synthetic_replay.ok && synthetic_replay.error == 0 && synthetic_replay.kind == errors.Kind.System)
  benchmark := testing.benchmark_start(1)
  empty_benchmark := testing.benchmark_start(0)
  events: [1]profile.Event = []
  trace := profile.trace(events[..])
  filters: [4]Filter = [Filter{code:32,k:0}, Filter{code:21,jf:1,k:228}, Filter{code:6,k:327681}, Filter{code:6,k:2147418112}]
  program := Program{length:4,filter:&filters[0]}
  require(#syscall(157,38,1,0,0,0)==0)
  require(#syscall(317,1,0,&program)==0)
  finished := profile.finish(&trace, span)
  require(!finished.ok && finished.error == -1 && finished.kind == errors.Kind.PermissionDenied && trace.failed && trace.count == 0)
  replay := profile.finish(&trace, profile.Span{})
  require(!replay.ok && replay.error == finished.error && replay.kind == finished.kind)
  elapsed := testing.benchmark_elapsed(&benchmark)
  require(!elapsed.ok && elapsed.error == -1 && elapsed.kind == errors.Kind.PermissionDenied)
  each := testing.benchmark_nanoseconds_each(&benchmark)
  require(!each.ok && each.error == -1 && each.kind == errors.Kind.PermissionDenied)
  descriptors: [0]net.PollDescriptor = []
  failed_start := testing.benchmark_start(0)
  empty_failure := testing.benchmark_nanoseconds_each(&failed_start)
  require(!empty_failure.ok && empty_failure.error == -1 && empty_failure.kind == errors.Kind.PermissionDenied)
  zero_each := testing.benchmark_nanoseconds_each(&empty_benchmark)
  require(zero_each.ok && zero_each.value == 0)
  polled := net.poll(descriptors[..], 10)
  require(!polled.ok && polled.error == -1 && polled.kind == errors.Kind.PermissionDenied)
  queue := net.event_queue()
  require(queue.ok)
  defer _ = net.close(queue.value)
  notifications: [1]net.Event = []
  waited := net.event_wait(queue.value, notifications[..], 10)
  require(!waited.ok && waited.error == -1 && waited.kind == errors.Kind.PermissionDenied)
  arena := mem.arena_create(0)
  defer mem.arena_release(arena)
  server := net.ipv4(127,0,0,1,53)
  resolved := dns.resolve_ipv4(arena, "example.test", &server, 10)
  require(!resolved.ok && resolved.error == -1 && resolved.kind == errors.Kind.PermissionDenied && #len(resolved.value) == 0 && mem.arena_mark(arena) == mem.arena_start(arena))
  arguments: [3][]const u8 = ["sh", "-c", "exit 0"]
  captured := process.capture(arena, "/bin/sh", arguments[..], process.Options{}, process.CaptureOptions{timeout_milliseconds:10})
  require(!captured.ok && captured.error == -1 && captured.kind == errors.Kind.PermissionDenied && #len(captured.output) == 0 && #len(captured.errors) == 0 && mem.arena_mark(arena) == mem.arena_start(arena))
  status: i32 = 0
  require(#syscall(61,-1,&status,1,0) == -10)
}
'''

def main():
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        print('SKIP clock consumers: Linux x86_64 seccomp required')
        return
    with tempfile.TemporaryDirectory(prefix='dyn-clock-consumers-') as tmp:
        root=Path(tmp)
        (root/'main.dyn').write_text(SOURCE)
        env=dict(os.environ,DYN_SDK=str(ROOT))
        for mode in ('debug','release'):
            output=root/'probe'
            subprocess.run([DYN,'build',str(root),'--quiet','--no-cache','--'+mode,'--output',str(output)],env=env,check=True,timeout=120)
            subprocess.run([str(output)],check=True,timeout=10)
            print('PASS clock consumers permission failure, capture rollback/reaping',mode)
if __name__=='__main__':main()
