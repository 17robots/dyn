#!/usr/bin/env python3
"""Shared keyed state: current-frame lookup, caller identity and recycling."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
SOURCE = r'''use "std/ui/box" box
use "std/mem" mem
fn check(ok: bool, why: []const u8) { if !ok { #panic(why) } }
fn measure(data: rawptr, text: []const u8) f32 { _ = data
  return #cast(f32, #len(text)) * 8.0 }
fn start(state: *box.State, frame: *mem.Arena) {
  mem.arena_reset(frame)
  box.begin(state, frame, box.Input{}, 100.0, 100.0, 0.02)
}
fn main() {
  persistent := mem.arena_create(0)
  frame := mem.arena_create(0)
  defer { mem.arena_release(frame)
    mem.arena_release(persistent) }
  state := box.create(persistent, measure, nil, 16.0)
  key := box.key_bytes(0, "explicit###identity")
  check(key != box.key(0, "explicit###identity"), "explicit identity does not parse label suffix")
  encoded: [8]u8 = [35,35,35,0,0,0,0,0]
  check(box.key_number(7, 0x232323) == box.key_bytes(7, encoded[..]), "numeric little-endian full bytes")
  check(box.key(7, "shown###identity") == box.key(7, "changed###identity"), "label suffix remains stable")
  start(state, frame)
  first := box.build_key(state, 0, key, "first")
  second := box.build_key(state, 0, key, "second")
  check(first != second && first.key != second.key, "duplicate identities derive separate boxes")
  first.user_data = 31
  second.user_data = 47
  second_key := second.key
  check(box.find(state, key) == first && box.find(state, second_key) == second, "lookup current frame")
  box.layout(state)
  start(state, frame)
  check(box.find(state, key) == nil, "previous frame is not current lookup")
  repeated := box.build_key(state, 0, key, "changed")
  repeated_second := box.build_key(state, 0, key, "changed second")
  check(repeated == first && repeated.user_data == 31 && repeated_second.key == second_key && repeated_second.user_data == 47, "caller identities persist across builds")
  box.layout(state)
  for i in 0..3 {
    start(state, frame)
    _ = box.build_key(state, 0, box.key_number(99, #cast(u64, i)), "temporary")
    box.layout(state)
  }
  start(state, frame)
  fresh := box.build_key(state, 0, key, "fresh")
  check(fresh.user_data == 0 && box.find(state, second_key) == nil, "expired caller state clears on recycle")
  box.layout(state)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-box-cache-') as directory:
    work = Path(directory)
    (work/'main.dyn').write_text(SOURCE)
    for flags in (['--debug'], ['--release'], ['--release', '--opt-level', '3']):
        output = work/'test'
        subprocess.run([DYN, 'build', str(work), *flags, '--quiet', '--output', str(output)], check=True, timeout=300)
        subprocess.run([str(output)], check=True, timeout=90)
    for target in ('aarch64-linux', 'riscv64-linux', 'x86_64-macos', 'aarch64-macos', 'x86_64-windows', 'aarch64-windows', 'wasm32-wasi'):
        output = work/target
        subprocess.run([DYN, 'build', str(work), '--release', '--target', target, '--quiet', '--output', str(output)], check=True, timeout=300)
        emulator = {'aarch64-linux': 'qemu-aarch64', 'riscv64-linux': 'qemu-riscv64', 'x86_64-windows': 'wine'}.get(target)
        if emulator and shutil.which(emulator):
            subprocess.run([emulator, str(output)], check=True, timeout=120)
        if target == 'wasm32-wasi' and shutil.which('node'):
            script = "const {WASI}=require('node:wasi'),fs=require('node:fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
            subprocess.run(['node','--no-warnings','-e',script,str(output)],check=True,timeout=120)
print('PASS shared box cache: raw/numeric keys, label suffixes, current-frame lookup, persistent caller identity, duplicates and recycled state (debug/O2/O3 and cross-targets)')
