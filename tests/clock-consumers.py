#!/usr/bin/env python3
"""A refused clock reads zero and its std consumers keep working; Linux x86-64
seccomp only."""
import os
from pathlib import Path
import platform
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
SOURCE = '''use time "std/time"
use profile "std/profile"
use testing "std/testing"
use net "std/net"
use dns "std/net/dns"
use process "std/process"
use mem "std/mem"
struct Filter { code: u16, jt: u8, jf: u8, k: u32 }
struct Program { length: u16, filter: *Filter }
fn require(ok: bool) { if !ok { #panic("clock consumer contract") } }
fn resolve_fails(arena: *mem.Arena, server: *const net.Ipv4Address) bool {
  _ = dns.resolve_ipv4(arena, "example.test", server, 10) catch { return true }
  return false
}
fn main() {
  span := profile.begin("clock")
  benchmark := testing.benchmark_start(1)
  empty_benchmark := testing.benchmark_start(0)
  events: [1]profile.Event
  trace := profile.trace(events[..])
  filters: [4]Filter = [Filter{code:32,k:0}, Filter{code:21,jf:1,k:228}, Filter{code:6,k:327681}, Filter{code:6,k:2147418112}]
  program := Program{length:4,filter:&filters[0]}
  require(#syscall(157,38,1,0,0,0)==0)
  require(#syscall(317,1,0,&program)==0)
  // The clock now reads zero. Its consumers keep working: nothing fails.
  profile.finish(&trace, span)
  profile.finish(&trace, profile.Span{})
  require(trace.count == 1 && trace.dropped == 1)
  _ = testing.benchmark_elapsed(&benchmark)
  require(testing.benchmark_nanoseconds_each(&empty_benchmark) == 0)
  descriptors: [0]net.PollDescriptor
  polled := net.poll(descriptors[..], 10) catch { #panic("net.poll") }
  require(polled == 0)
  queue := net.event_queue() catch { #panic("net.event_queue") }
  defer net.close(queue)
  notifications: [1]net.Event
  waited := net.event_wait(queue, notifications[..], 10) catch { #panic("net.event_wait") }
  require(waited == 0)
  arena := mem.arena_alloc(0)
  defer mem.arena_release(arena)
  server := net.ipv4(127,0,0,1,53)
  require(resolve_fails(arena, &server) && mem.arena_mark(arena) == mem.ArenaHeader)
  arguments: [3][]const u8 = ["sh", "-c", "exit 0"]
  captured := process.capture(arena, "/bin/sh", arguments[..], process.Options{}, process.CaptureOptions{timeout_milliseconds:1000}) catch { #panic("capture") }
  require(captured.exit.finished && captured.exit.code == 0)
  wait_status: i32 = 0
  require(#syscall(61,-1,&wait_status,1,0) == -10)
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
            print('PASS clock consumers with a refused clock: profile, benchmark, poll, events, DNS, capture',mode)
if __name__=='__main__':main()
