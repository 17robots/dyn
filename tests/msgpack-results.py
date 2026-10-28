#!/usr/bin/env python3
"""MessagePack type families, integer extremes and bounded malformed input."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use "std/encoding/msgpack" mp
use "std/mem" mem
use "std/errors" errors
use "std/bytes" bytes
fn check(ok: bool) { if !ok { #panic("msgpack contract") } }
fn bad(source: []const u8) {
 state := mp.reader(source)
 item := mp.next(&state)
 for item.ok { item = mp.next(&state) }
 check(item.kind == errors.Kind.InvalidInput)
 again := mp.next(&state)
 check(again.kind == item.kind && again.offset == item.offset)
}
fn main() {
 arena := mem.arena_create(0)
 defer { mem.arena_release(arena) }
 golden := "\x82\xa1a\x93\x00\xcc\x80\xff\xa1b\xc4\x02hi"
 state := mp.reader(golden)
 tokens: [9]mp.Token = []
 count: usize = 0
 item := mp.next(&state)
 for item.ok { tokens[count] = item.value
 count += 1
 item = mp.next(&state) }
 check(item.kind == errors.Kind.None && count == 8)
 check(tokens[0].kind == mp.Kind.Map && tokens[0].value == 2)
 check(tokens[2].kind == mp.Kind.Array && tokens[2].value == 3)
 check(tokens[5].integer == -1 && bytes.equal(tokens[7].bytes,"hi"))
 encoded := mp.encode(arena,tokens[..count])
 check(encoded.ok)
 state = mp.reader(encoded.value)
 for token in tokens[..count] {
  value := mp.next(&state)
  check(value.ok && value.value.kind == token.kind && value.value.value == token.value && value.value.integer == token.integer && bytes.equal(value.value.bytes,token.bytes))
 }
 check(mp.next(&state).kind == errors.Kind.None && !mp.next(&state).ok)
 // Every header is either complete or a structured failure, never a trap.
 raw: [20]u8 = []
 for tag in 0..256 {
  raw[0] = #cast(u8,tag)
  state = mp.reader(raw[..])
  result := mp.next(&state)
  for result.ok { result = mp.next(&state) }
  check(result.kind == errors.Kind.None || result.kind == errors.Kind.InvalidInput)
 }
 bad("\xc1")
 bad("\x91")
 bad("\x81\x00")
 bad("\xdb\xff\xff\xff\xff")
 bad("\xc7\x01")
 bad("\xcf\x00")
 extrema: [7]mp.Token = [mp.Token{kind:mp.Kind.Unsigned,value:0xffffffffffffffff},mp.Token{kind:mp.Kind.Signed,integer:-9223372036854775808},mp.Token{kind:mp.Kind.Signed,integer:9223372036854775807},mp.Token{kind:mp.Kind.Float,real:-1.5},mp.Token{kind:mp.Kind.Extension,extension:-1,bytes:"123456789012"},mp.Token{kind:mp.Kind.Text,bytes:"\xff\x00"},mp.Token{kind:mp.Kind.Bool,boolean:true}]
 encoded = mp.encode(arena,extrema[..])
 check(encoded.ok)
 state = mp.reader(encoded.value)
 for expected in extrema {
  result := mp.next(&state)
  check(result.ok && result.value.kind == expected.kind && result.value.value == expected.value && result.value.integer == expected.integer && result.value.real == expected.real && result.value.extension == expected.extension && result.value.boolean == expected.boolean && bytes.equal(result.value.bytes,expected.bytes))
 }
 state = mp.reader("\xca\x3f\xc0\x00\x00")
 check(mp.next(&state).value.real == 1.5)
 mark := mem.arena_mark(arena)
 invalid: [1]mp.Token = [mp.Token{kind:mp.Kind.Array,value:1}]
 check(mp.encode(arena,invalid[..]).kind == errors.Kind.InvalidInput && mem.arena_mark(arena) == mark)
 deep: [130]u8 = []
 for i in 0..129 { deep[i] = 0x91 }
 state = mp.reader(deep[..])
 for i in 0..64 { check(mp.next(&state).ok) }
 check(mp.next(&state).kind == errors.Kind.Capacity)
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-msgpack-') as directory:
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
print('PASS MessagePack: all wire types, extrema, nesting, malformed input and cross-targets')
