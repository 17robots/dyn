#!/usr/bin/env python3
"""MessagePack type families, integer extremes and bounded malformed input."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use parse "std/parse"
use mp "std/encoding/msgpack"
use mem "std/mem"
use bytes "std/bytes"
// code: 0 none, 1 Invalid, 2 TooLarge.
fn code_of(err: parse.ParseErr) u8 {
 case err {
  .Invalid(_) => { return 1 }
  .TooLarge(_) => { return 2 }
  .Unsupported(_) => { return 2 }
 }
}
struct Got { value: mp.Token, offset: usize, found: bool, code: u8 }
fn next(state: *mp.Reader) Got {
 item := mp.next(state) catch err { return Got{ offset: state.start, code: code_of(err) } }
 return Got{ value: item, offset: state.start, found: !state.ended }
}
struct Encoded { value: []u8, code: u8 }
fn encode(arena: *mem.Arena, items: []const mp.Token) Encoded {
 value := mp.encode(arena, items) catch err { return Encoded{ code: code_of(err) } }
 return Encoded{ value: value }
}
fn check(ok: bool) { if !ok { #panic("msgpack contract") } }
fn bad(source: []const u8) {
 state := mp.reader(source)
 item := next(&state)
 for item.found { item = next(&state) }
 check(item.code == 1)
 again := next(&state)
 check(again.code == item.code && again.offset == item.offset)
}
fn main() {
 arena := mem.arena_alloc(0)
 defer { mem.arena_release(arena) }
 golden := "\x82\xa1a\x93\x00\xcc\x80\xff\xa1b\xc4\x02hi"
 state := mp.reader(golden)
 tokens: [9]mp.Token
 count: usize = 0
 item := next(&state)
 for item.found { tokens[count] = item.value
 count += 1
 item = next(&state) }
 check(item.code == 0 && count == 8)
 check(tokens[0].kind == mp.Kind.Map && tokens[0].value == 2)
 check(tokens[2].kind == mp.Kind.Array && tokens[2].value == 3)
 check(tokens[5].integer == -1 && bytes.equal(tokens[7].bytes,"hi"))
 encoded := encode(arena,tokens[..count])
 check(encoded.code == 0)
 state = mp.reader(encoded.value)
 for token in tokens[..count] {
  value := next(&state)
  check(value.found && value.value.kind == token.kind && value.value.value == token.value && value.value.integer == token.integer && bytes.equal(value.value.bytes,token.bytes))
 }
 check(next(&state).code == 0 && !next(&state).found)
 // Every header is either complete or a structured failure, never a trap.
 raw: [20]u8
 for tag in 0..256 {
  raw[0] = #cast(u8,tag)
  state = mp.reader(raw[..])
  result := next(&state)
  for result.found { result = next(&state) }
  check(result.code == 0 || result.code == 1)
 }
 bad("\xc1")
 bad("\x91")
 bad("\x81\x00")
 bad("\xdb\xff\xff\xff\xff")
 bad("\xc7\x01")
 bad("\xcf\x00")
 extrema: [7]mp.Token = [mp.Token{kind:mp.Kind.Unsigned,value:0xffffffffffffffff},mp.Token{kind:mp.Kind.Signed,integer:-9223372036854775808},mp.Token{kind:mp.Kind.Signed,integer:9223372036854775807},mp.Token{kind:mp.Kind.Float,real:-1.5},mp.Token{kind:mp.Kind.Extension,extension:-1,bytes:"123456789012"},mp.Token{kind:mp.Kind.Text,bytes:"\xff\x00"},mp.Token{kind:mp.Kind.Bool,boolean:true}]
 encoded = encode(arena,extrema[..])
 check(encoded.code == 0)
 state = mp.reader(encoded.value)
 for expected in extrema {
  result := next(&state)
  check(result.found && result.value.kind == expected.kind && result.value.value == expected.value && result.value.integer == expected.integer && result.value.real == expected.real && result.value.extension == expected.extension && result.value.boolean == expected.boolean && bytes.equal(result.value.bytes,expected.bytes))
 }
 state = mp.reader("\xca\x3f\xc0\x00\x00")
 check(next(&state).value.real == 1.5)
 mark := mem.arena_mark(arena)
 invalid: [1]mp.Token = [mp.Token{kind:mp.Kind.Array,value:1}]
 check(encode(arena,invalid[..]).code == 1 && mem.arena_mark(arena) == mark)
 deep: [130]u8
 for i in 0..129 { deep[i] = 0x91 }
 state = mp.reader(deep[..])
 for i in 0..64 { check(next(&state).found) }
 check(next(&state).code == 2)
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
