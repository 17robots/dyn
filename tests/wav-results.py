#!/usr/bin/env python3
"""PCM/IEEE WAVE references, extensible GUIDs, padding, round-trip and errors."""
import io
import os
from pathlib import Path
import struct
import subprocess
import shutil
import tempfile
import wave
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
source=r'''use "std/audio/wav" wav
use "std/io" io
use "std/mem" mem
use "std/fail"
use "std/fs" fs
fn check(ok: bool) { if !ok { #panic("WAV contract") } }
fn decode_fails(arena: *mem.Arena, data: []const u8) bool {
  status: fail.Status
  _ = wav.decode(arena, &status, data)
  return status.failed
}
fn main() {
  status := fail.Status{ on_failure: fail.panic_on_failure }
  arena := mem.arena_alloc(0)
  defer { mem.arena_release(arena) }
  samples: [6]f32 = [-1.0,-0.5,0.0,0.25,0.5,1.0]
  audio := wav.Audio{ samples: samples[..], rate: 48000, channels: 2 }
  formats: [5]wav.Encoding = [wav.Encoding.Pcm8,wav.Encoding.Pcm16,wav.Encoding.Pcm24,wav.Encoding.Pcm32,wav.Encoding.Float32]
  paths: [5][]const u8 = ["8.wav","16.wav","24.wav","32.wav","float.wav"]
  for i in 0..5 {
    encoded := wav.encode(arena, &status, &audio, formats[i])
    check(fs_write_file(paths[i],encoded))
    decoded := wav.decode(arena, &status, encoded)
    check(decoded.rate == 48000 && decoded.channels == 2 && #len(decoded.samples) == 6)
    for j in 0..6 {
      difference := decoded.samples[j] - samples[j]
      check(difference >= -0.008 && difference <= 0.008)
    }
    before := mem.arena_mark(arena)
    for length in 0..#len(encoded) {
      check(decode_fails(arena, encoded[..length]) && mem.arena_mark(arena) == before)
    }
  }
  audio.channel_mask = 3
  extended := wav.encode(arena, &status, &audio, wav.Encoding.Pcm24)
  decoded := wav.decode(arena, &status, extended)
  check(decoded.channel_mask == 3)
  check(fs_write_file("extended.wav",extended))
  floating := wav.encode(arena, &status, &audio, wav.Encoding.Float32)
  _ = wav.decode(arena, &status, floating)
  before := mem.arena_mark(arena)
  audio.channel_mask = 1
  invalid: fail.Status
  _ = wav.encode(arena, &invalid, &audio, wav.Encoding.Pcm16)
  check(invalid.failure.kind == fail.Kind.InvalidInput)
  check(mem.arena_mark(arena) == before)
  reference_file: fail.Status
  reference := fs.read_all(arena, &reference_file, "reference.wav", 10000)
  check(!reference_file.failed)
  decoded = wav.decode(arena, &status, reference)
  check(#len(decoded.samples) == 5)
  expected: [5]f32 = [-1.0,-0.5,0.0,0.5,0.999969482421875]
  for i in 0..5 { check(decoded.samples[i] == expected[i]) }
  // Every individual header/data mutation must return or decode, never trap.
  work := mem.push_array(u8,arena,#len(reference))
  _ = mem.copy(work,reference)
  for at in 0..#len(work) {
    for bit in 0..8 {
      saved := work[at]
      work[at] ^= #cast(u8,(1 << bit))
      checkpoint := mem.arena_mark(arena)
      _ = decode_fails(arena,work)
      mem.arena_rewind(arena,checkpoint)
      work[at] = saved
    }
  }
}

// Writes data to path; whether it worked.
fn fs_write_file(path: []const u8, data: []const u8) bool {
  status: fail.Status
  fs.write_all(&status, path, data)
  return !status.failed
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-wav-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(source)
    output=io.BytesIO()
    with wave.open(output,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(22050)
        wav.writeframes(struct.pack('<5h',-32768,-16384,0,16384,32767))
    (work/'reference.wav').write_bytes(output.getvalue())
    for mode in ('--debug','--release'):
        subprocess.run([DYN,'build',str(work),mode,'--quiet','--no-cache','--output',str(work/'program')],check=True,timeout=300)
        subprocess.run([str(work/'program')],cwd=work,check=True,timeout=60)
        for bits in (8,16,24,32):
            with wave.open(str(work/f'{bits}.wav'),'rb') as decoded:
                assert decoded.getnchannels()==2 and decoded.getframerate()==48000 and decoded.getnframes()==3
                raw=decoded.readframes(3)
                expected=[-1.0,-0.5,0.0,0.25,0.5,1.0]
                maximum=1<<(bits-1)
                # Use the same explicitly documented tie direction, independently via floor.
                import math
                values=[min(maximum-1,max(-maximum,math.floor(x*maximum+0.5))) for x in expected]
                oracle=b''.join(bytes([x+128]) if bits==8 else int(x).to_bytes(bits//8,'little',signed=True) for x in values)
                assert raw==oracle,(bits,raw,oracle)
        data=(work/'float.wav').read_bytes()
        assert data[12:16]==b'fmt ' and data[38:42]==b'fact' and data[50:54]==b'data'
        assert data[58:]==struct.pack('<6f',-1,-.5,0,.25,.5,1)
        with wave.open(str(work/'extended.wav'),'rb') as extended:
            assert extended.getnchannels()==2 and extended.getsampwidth()==3
    core = r'''use "std/fail"
use "std/audio/wav" wav
use "std/io" io
use "std/mem" mem
fn check(ok: bool) { if !ok { #panic("WAV portable") } }
fn main() {
  status := fail.Status{ on_failure: fail.panic_on_failure }
  arena := mem.arena_alloc(0)
  defer { mem.arena_release(arena) }
  samples: [6]f32 = [-1.0,-0.5,0.0,0.25,0.5,1.0]
  audio := wav.Audio{ samples: samples[..], rate: 48000, channels: 2, channel_mask: 3 }
  formats: [5]wav.Encoding = [wav.Encoding.Pcm8,wav.Encoding.Pcm16,wav.Encoding.Pcm24,wav.Encoding.Pcm32,wav.Encoding.Float32]
  for encoding in formats {
    encoded := wav.encode(arena, &status,&audio,encoding)
    decoded := wav.decode(arena, &status, encoded)
    check(decoded.channels == 2 && decoded.rate == 48000 && decoded.channel_mask == 3)
    for i in 0..6 { difference := samples[i] - decoded.samples[i]
      check(difference <= 0.008 && difference >= -0.008) }
  }
}
'''
    (work/'main.dyn').write_text(core)
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
        output=work/target
        subprocess.run([DYN,'build',str(work),'--target',target,'--release','--quiet','--output',str(output)],check=True,timeout=300)
        emulator={'aarch64-linux':'qemu-aarch64','riscv64-linux':'qemu-riscv64','x86_64-windows':'wine'}.get(target)
        if emulator and shutil.which(emulator): subprocess.run([emulator,str(output)],check=True,timeout=60)
        if target=='wasm32-wasi' and shutil.which('node'):
            script="const {WASI}=require('node:wasi'),fs=require('node:fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
            subprocess.run(['node','--no-warnings','-e',script,str(output)],check=True,timeout=60)
print('PASS WAV PCM 8/16/24/32, float32, extensible, Python wave oracles, truncations, mutations and ownership')
