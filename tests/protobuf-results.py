#!/usr/bin/env python3
"""Official wire golden, scalar extremes, groups and sticky parse failures."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "std/encoding/protobuf" pb
use "std/mem" mem
use "std/bytes" bytes
use "std/errors" errors
fn check(ok: bool) { if !ok { #panic("protobuf contract") } }
fn bad(source: []const u8) {
  state := pb.reader(source)
  result := pb.next(&state)
  for result.ok { result = pb.next(&state) }
  check(result.kind == errors.Kind.InvalidInput)
  again := pb.next(&state)
  check(again.kind == result.kind && again.offset == result.offset)
}
fn main() {
  arena := mem.Arena{}
  defer { mem.arena_release(&arena) }
  fields: [7]pb.Field = [pb.Field{ number: 1, wire: pb.Wire.Varint, value: 150 },
    pb.Field{ number: 2, wire: pb.Wire.Fixed64, value: 0x0123456789abcdef },
    pb.Field{ number: 3, wire: pb.Wire.Bytes, bytes: "hi\x00" },
    pb.Field{ number: 4, wire: pb.Wire.Fixed32, value: 0x89abcdef },
    pb.Field{ number: 5, wire: pb.Wire.StartGroup },
    pb.Field{ number: 1, wire: pb.Wire.Varint, value: 0xffffffffffffffff },
    pb.Field{ number: 5, wire: pb.Wire.EndGroup }]
  encoded := pb.encode(&arena,fields[..])
  golden := "\x08\x96\x01\x11\xef\xcd\xab\x89\x67\x45\x23\x01\x1a\x03hi\x00\x25\xef\xcd\xab\x89\x2b\x08\xff\xff\xff\xff\xff\xff\xff\xff\xff\x01\x2c"
  check(encoded.ok && bytes.equal(encoded.value,golden))
  state := pb.reader(golden)
  for expected in fields {
    result := pb.next(&state)
    check(result.ok && result.value.number == expected.number && result.value.wire == expected.wire && result.value.value == expected.value && bytes.equal(result.value.bytes,expected.bytes))
  }
  check(!pb.next(&state).ok && pb.next(&state).kind == errors.Kind.None)
  integers: [7]i64 = [-9223372036854775808,-500,-1,0,1,500,9223372036854775807]
  for value in integers { check(pb.unzigzag(pb.zigzag(value)) == value) }
  check(pb.zigzag(-1) == 1 && pb.zigzag(500) == 1000 && pb.zigzag(-9223372036854775808) == 0xffffffffffffffff)
  bad("\x00")
  bad("\x0e")
  bad("\x08\x80")
  bad("\x08\xff\xff\xff\xff\xff\xff\xff\xff\xff\x02")
  bad("\x09\x00")
  bad("\x0a\x02x")
  bad("\x0b\x14")
  bad("\x0b")
  bad("\x0c")
  deep: [65]u8 = []
  for i in 0..65 { deep[i] = 11 }
  state = pb.reader(deep[..])
  for i in 0..64 { check(pb.next(&state).ok) }
  check(pb.next(&state).kind == errors.Kind.Capacity && pb.next(&state).kind == errors.Kind.Capacity)
  mark := mem.arena_mark(&arena)
  invalid: [1]pb.Field = [pb.Field{ number: 0 }]
  check(pb.encode(&arena,invalid[..]).kind == errors.Kind.InvalidInput && mem.arena_mark(&arena) == mark)
  invalid[0] = pb.Field{ number: 1, wire: pb.Wire.Fixed32, value: 0x100000000 }
  check(pb.encode(&arena,invalid[..]).kind == errors.Kind.InvalidInput && mem.arena_mark(&arena) == mark)
  invalid[0] = pb.Field{ number: 1, wire: pb.Wire.StartGroup }
  check(pb.encode(&arena,invalid[..]).kind == errors.Kind.InvalidInput && mem.arena_mark(&arena) == mark)
  fields[0] = pb.Field{ number: 536870911, value: 0xffffffffffffffff }
  encoded = pb.encode(&arena,fields[..1])
  state = pb.reader(encoded.value)
  result := pb.next(&state)
  check(encoded.ok && result.ok && result.value.number == 536870911 && result.value.value == 0xffffffffffffffff)
  // Every cut is either a complete shorter message or a structured failure.
  for length in 0..#len(golden) {
    state = pb.reader(golden[..length])
    item := pb.next(&state)
    for item.ok { item = pb.next(&state) }
    check(item.kind == errors.Kind.None || item.kind == errors.Kind.InvalidInput)
  }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-protobuf-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(SOURCE)
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'program'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--no-cache','--output',str(output)],check=True,timeout=300)
        subprocess.run([str(output)],check=True,timeout=30)
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
        output=work/target
        subprocess.run([DYN,'build',str(work),'--target',target,'--release','--quiet','--output',str(output)],check=True,timeout=300)
        emulator={'aarch64-linux':'qemu-aarch64','riscv64-linux':'qemu-riscv64','x86_64-windows':'wine'}.get(target)
        if emulator and shutil.which(emulator): subprocess.run([emulator,str(output)],check=True,timeout=60)
        if target=='wasm32-wasi' and shutil.which('node'):
            script="const {WASI}=require('node:wasi'),fs=require('fs');(async()=>{const wasi=new WASI({version:'preview1',returnOnExit:true});const {instance}=await WebAssembly.instantiate(fs.readFileSync(process.argv[1]),{wasi_snapshot_preview1:wasi.wasiImport});process.exitCode=wasi.start(instance);})().catch(e=>{console.error(e);process.exit(1)});"
            subprocess.run(['node','--no-warnings','-e',script,str(output)],check=True,timeout=60)
print('PASS protobuf: wire golden, fixed/varint/length fields, groups, ZigZag extremes, sticky failures, allocation preservation and cross-targets')
