#!/usr/bin/env python3
"""Real contended native mutex/condition/semaphore/once contracts."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build'/('dyn-release.exe' if os.name == 'nt' else 'dyn-release'))).resolve())
SOURCE = '''use "std/sync"
use "std/thread"
struct Shared {
  mutex: sync.Mutex, condition: sync.Condition, gate: sync.Semaphore,
  once: sync.Once, arrived: u32, completed: u32, total: u64, value: u64
}
fn worker(context: rawptr) isize {
  shared := #cast(*Shared) context
  sync.lock(&shared.mutex)
  shared.arrived += 1
  sync.condition_broadcast(&shared.condition)
  sync.unlock(&shared.mutex)
  sync.semaphore_wait(&shared.gate)
  for i in 0..2000 {
    sync.lock(&shared.mutex)
    shared.total += 1
    sync.unlock(&shared.mutex)
  }
  if sync.once_begin(&shared.once) {
    shared.value += 42
    sync.once_complete(&shared.once)
  }
  if shared.value != 42 { #panic("once publication") }
  sync.lock(&shared.mutex)
  shared.completed += 1
  sync.condition_signal(&shared.condition)
  sync.unlock(&shared.mutex)
  return 0
}
fn main() {
  failed := thread.Thread{}
  if thread.spawn_with_size(&failed, ~#cast(usize) 0, &worker, nil) >= 0 || thread.join(&failed) != 0 { #panic("failed spawn ownership/error") }
  shared := Shared{}
  if !sync.try_lock(&shared.mutex) { #panic("initial trylock") }
  if sync.try_lock(&shared.mutex) { #panic("recursive trylock") }
  sync.unlock(&shared.mutex)
  threads: [4]thread.Thread = []
  for i in 0..4 {
    if thread.spawn_with_size(&threads[i], 131072, &worker, #cast(rawptr) &shared) < 0 { #panic("spawn") }
  }
  sync.lock(&shared.mutex)
  for shared.arrived != 4 { sync.condition_wait(&shared.condition, &shared.mutex) }
  sync.unlock(&shared.mutex)
  for i in 0..4 { sync.semaphore_post(&shared.gate) }
  sync.lock(&shared.mutex)
  for shared.completed != 4 { sync.condition_wait(&shared.condition, &shared.mutex) }
  if shared.total != 8000 { #panic("lost mutex updates") }
  sync.unlock(&shared.mutex)
  for i in 0..4 { if thread.join(&threads[i]) != 0 { #panic("join") } }
  if sync.semaphore_try_wait(&shared.gate) || sync.once_begin(&shared.once) { #panic("consumed state") }
  sync.semaphore_post(&shared.gate)
  if !sync.semaphore_try_wait(&shared.gate) { #panic("semaphore try") }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-native-sync-') as temporary:
    work=Path(temporary); (work/'main.dyn').write_text(SOURCE)
    for target in (['x86_64-linux','aarch64-linux','aarch64-macos','x86_64-windows'] if '--cross' in sys.argv else [None]):
        for mode in ['--debug','--release']:
            output=work/('probe.exe' if target=='x86_64-windows' or os.name=='nt' else 'probe')
            command=[DYN,'build',str(work),mode,'--quiet','--no-cache','--output',str(output)]
            if target: command+=['--target',target]
            subprocess.run(command,check=True,timeout=120)
            if target is None: subprocess.run([str(output)],check=True,timeout=20)
print('PASS contended native synchronization (debug/release)' if '--cross' not in sys.argv else 'PASS synchronization cross-links; foreign execution requires native CI')
