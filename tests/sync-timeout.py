#!/usr/bin/env python3
"""Timed conditions: real pthread signal, timeout, EINTR budget and mutex ownership."""
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "std/sync"
use "std/time"
use "std/errors" errors
#link("sync_timeout_probe")
extern fn start "probe_start"(entry: fn(rawptr) rawptr, context: rawptr) i32
extern fn join "probe_join"() i32
extern fn interrupts "probe_interrupts"() i32
extern fn finish_interrupts "probe_finish_interrupts"() i32
struct Shared { mutex: sync.Mutex, condition: sync.Condition, ready: bool }
fn check(value: bool) { if !value { #panic("condition timeout") } }
fn worker(context: rawptr) rawptr {
  shared := #cast(*Shared,context)
  check(time.sleep(10*time.Millisecond).ok)
  sync.lock(&shared.mutex)
  shared.ready = true
  sync.condition_signal(&shared.condition)
  sync.unlock(&shared.mutex)
  return nil
}
fn main() {
  shared := Shared{}
  sync.lock(&shared.mutex)
  invalid := sync.condition_wait_timeout(&shared.condition,&shared.mutex,-1)
  check(!invalid.ok && invalid.kind==errors.Kind.InvalidInput)
  check(!sync.try_lock(&shared.mutex))
  zero := sync.condition_wait_timeout(&shared.condition,&shared.mutex,0)
  check(zero.ok && zero.status==sync.ConditionWaitStatus.TimedOut)
  check(!sync.try_lock(&shared.mutex))
  before := time.monotonic_now()
  check(before.ok)
  timeout := sync.condition_wait_timeout(&shared.condition,&shared.mutex,15*time.Millisecond)
  after := time.monotonic_now()
  elapsed := time.elapsed(before.value,after.value)
  check(timeout.ok && timeout.status==sync.ConditionWaitStatus.TimedOut)
  check(elapsed.ok && elapsed.value>=15*time.Millisecond)
  check(!sync.try_lock(&shared.mutex))
  check(start(worker,#cast(rawptr,&shared))==0)
  for !shared.ready {
    result := sync.condition_wait_timeout(&shared.condition,&shared.mutex,time.Second)
    check(result.ok && result.status==sync.ConditionWaitStatus.Signaled)
  }
  check(!sync.try_lock(&shared.mutex))
  sync.unlock(&shared.mutex)
  check(join()==0)
  sync.lock(&shared.mutex)
  check(interrupts()==0)
  before = time.monotonic_now()
  interrupted := sync.condition_wait_timeout(&shared.condition,&shared.mutex,80*time.Millisecond)
  after = time.monotonic_now()
  elapsed = time.elapsed(before.value,after.value)
  check(interrupted.ok && interrupted.status==sync.ConditionWaitStatus.TimedOut)
  check(elapsed.ok && elapsed.value>=80*time.Millisecond && elapsed.value<400*time.Millisecond)
  check(!sync.try_lock(&shared.mutex))
  sync.unlock(&shared.mutex)
  check(finish_interrupts()==0)
}
'''
C=r'''#define _POSIX_C_SOURCE 200809L
#include <pthread.h>
#include <signal.h>
#include <time.h>
static pthread_t worker, sender, target;
static void ignore(int number){(void)number;}
static void *send_interrupts(void *unused){
 (void)unused;
 for(int i=0;i<100;i++){
  struct timespec delay={0,5000000}; nanosleep(&delay,0);
  pthread_kill(target,SIGUSR1);
 }
 return 0;
}
int probe_start(void *(*entry)(void *),void *context){return pthread_create(&worker,0,entry,context);}
int probe_join(void){return pthread_join(worker,0);}
int probe_interrupts(void){
 struct sigaction action={0}; action.sa_handler=ignore; sigemptyset(&action.sa_mask);
 if(sigaction(SIGUSR1,&action,0))return -1;
 target=pthread_self(); return pthread_create(&sender,0,send_interrupts,0);
}
int probe_finish_interrupts(void){return pthread_join(sender,0);}
'''
if not sys.platform.startswith('linux'):
    print('SKIP pthread/SIGUSR1 harness: Linux host required')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-sync-timeout-') as temporary:
    work=Path(temporary)
    (work/'main.dyn').write_text(SOURCE)
    (work/'probe.c').write_text(C)
    subprocess.run(['cc','-shared','-fPIC','-Wall','-Wextra','-Werror',str(work/'probe.c'),'-pthread','-o',str(work/'libsync_timeout_probe.so')],check=True)
    env=dict(os.environ,DYN_LIBRARY_PATH=str(work),LD_LIBRARY_PATH=str(work)+os.pathsep+os.environ.get('LD_LIBRARY_PATH',''))
    for mode in ('--debug','--release'):
        output=work/'test'
        subprocess.run([DYN,'build',str(work),mode,'--quiet','--no-cache','--output',str(output)],env=env,check=True,timeout=120)
        subprocess.run([str(output)],env=env,check=True,timeout=10)
    # Inject a native failure at the existing backend seam, keeping the public
    # wait loop, real atomics, monotonic clock and mutex implementation intact.
    package=work/'sync'
    shutil.copytree(ROOT/'std/sync',package)
    backend=package/'linux.dyn'
    text=backend.read_text()
    start=text.index('fn native_wait_timeout(')
    end=text.index('fn native_sync_error',start)
    text=text[:start]+"fn native_wait_timeout(address: *AtomicU32, expected: u32, duration: i64) isize {\n _ = address\n _ = expected\n _ = duration\n return -22\n}\n"+text[end:]
    backend.write_text(text)
    (work/'main.dyn').write_text("""use \"sync\" sync
use \"std/errors\" errors
fn main() {
 mutex := sync.mutex()
 condition := sync.condition()
 sync.lock(&mutex)
 result := sync.condition_wait_timeout(&condition,&mutex,1000000000)
 if result.ok || result.error != -22 || result.kind != errors.Kind.InvalidInput { #panic(\"native error\") }
 if sync.try_lock(&mutex) { #panic(\"mutex not reacquired\") }
 sync.unlock(&mutex)
}
""")
    subprocess.run([DYN,'build',str(work),'--release','--quiet','--no-cache','--output',str(work/'error')],check=True,timeout=120)
    subprocess.run([str(work/'error')],check=True,timeout=10)
    # Compile the actual Windows backend against address-wait fault stubs on
    # Linux. Native error 4 is not EINTR on Windows and must remain visible.
    windows=(ROOT/'std/sync/windows.dyn').read_text().replace('#target(kernel: windows)','#target(kernel: linux)')
    windows=windows.replace('extern fn wait_address "dyn_sync_wait"(address: *u32, expected: *const u32, size: usize, milliseconds: u32) i32',
        'fn wait_address(address: *u32, expected: *const u32, size: usize, milliseconds: u32) i32 {\n _ = address\n _ = expected\n _ = size\n _ = milliseconds\n return 0\n}')
    windows=windows.replace('extern fn wake_single "dyn_sync_single"(address: *u32)','fn wake_single(address: *u32) { _ = address }')
    windows=windows.replace('extern fn wake_all "dyn_sync_all"(address: *u32)','fn wake_all(address: *u32) { _ = address }')
    windows=windows.replace('extern fn wait_error "dyn_sync_error"() u32','fn wait_error() u32 { return 4 }')
    backend.write_text(windows)
    source=(work/'main.dyn').read_text().replace('result.error != -22','result.error != -4').replace('errors.Kind.InvalidInput','errors.Kind.System').replace('1000000000','10000000')
    (work/'main.dyn').write_text(source)
    subprocess.run([DYN,'build',str(work),'--release','--quiet','--no-cache','--output',str(work/'windows-error')],check=True,timeout=120)
    subprocess.run([str(work/'windows-error')],check=True,timeout=10)
print('PASS timed conditions: zero/negative, mutex reacquisition, signal, timeout, EINTR deadline (debug/release)')
