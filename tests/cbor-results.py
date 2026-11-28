#!/usr/bin/env python3
"""RFC 8949 examples, indefinite strings, tags and malformed CBOR."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import private_display  # hides the desktop display; see tests/private_display.py
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use parse "std/parse"
use cbor "std/encoding/cbor"
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
struct Got { value: cbor.Token, offset: usize, found: bool, code: u8 }
fn next(state: *cbor.Reader) Got {
 item := cbor.next(state) catch err { return Got{ offset: state.start, code: code_of(err) } }
 return Got{ value: item, offset: state.start, found: !state.ended }
}
struct Encoded { value: []u8, code: u8 }
fn encode(arena: *mem.Arena, items: []const cbor.Token) Encoded {
 value := cbor.encode(arena, items) catch err { return Encoded{ code: code_of(err) } }
 return Encoded{ value: value }
}
fn check(ok: bool) { if !ok { #panic("CBOR contract") } }
fn bad(source: []const u8) {
 state := cbor.reader(source)
 item := next(&state)
 for item.found { item = next(&state) }
 check(item.code == 1)
 again := next(&state)
 check(again.code == item.code && again.offset == item.offset)
}
fn main() {
 arena := mem.arena_alloc(0)
 defer { mem.arena_release(arena) }
 // RFC8949 Appendix A: {"a":1,"b":[2,3]}, indefinite [1,[2,3],4,5].
 golden := "\xa2\x61a\x01\x61b\x82\x02\x03"
 state := cbor.reader(golden)
 tokens: [20]cbor.Token
 count: usize = 0
 item := next(&state)
 for item.found { tokens[count] = item.value
 count += 1
 item = next(&state) }
 check(item.code == 0 && count == 7)
 encoded := encode(arena,tokens[..count])
 check(encoded.code == 0 && bytes.equal(encoded.value,golden))
 golden = "\x9f\x01\x82\x02\x03\x04\x05\xff"
 state = cbor.reader(golden)
 count = 0
 item = next(&state)
 for item.found { tokens[count] = item.value
 count += 1
 item = next(&state) }
 check(item.code == 0 && count == 8)
 encoded = encode(arena,tokens[..count])
 check(encoded.code == 0 && bytes.equal(encoded.value,golden))
 golden = "\xbf\x61a\x5f\x42ab\x41c\xff\x61b\x7f\x61d\x62ef\xff\xff"
 state = cbor.reader(golden)
 count = 0
 item = next(&state)
 for item.found { tokens[count] = item.value
 count += 1
 item = next(&state) }
 check(item.code == 0)
 encoded = encode(arena,tokens[..count])
 check(encoded.code == 0 && bytes.equal(encoded.value,golden))
 // Tags wrap one child, including nested containers and other tags.
 golden = "\x81\xd8\x20\xc0\x81\x61x"
 state = cbor.reader(golden)
 count = 0
 item = next(&state)
 for item.found { tokens[count] = item.value
 count += 1
 item = next(&state) }
 check(item.code == 0 && count == 5)
 encoded = encode(arena,tokens[..count])
 check(encoded.code == 0 && bytes.equal(encoded.value,golden))
 floats := "\xf9\x3e\x00\xfa\xbf\xc0\x00\x00\xfb\x3f\xf8\x00\x00\x00\x00\x00\x00\xf9\x00\x01\xf9\x80\x00\xf9\x7c\x00\xf9\x7e\x00"
 state = cbor.reader(floats)
 check(next(&state).value.real == 1.5)
 check(next(&state).value.real == -1.5)
 check(next(&state).value.real == 1.5)
 check(next(&state).value.real == 0.000000059604644775390625)
 check(#bitcast(u64,next(&state).value.real) == 0x8000000000000000)
 check(#bitcast(u64,next(&state).value.real) == 0x7ff0000000000000)
 nan := next(&state).value.real
 check(nan != nan)
 extremes: [8]cbor.Token = [cbor.Token{kind:cbor.Kind.Unsigned,value:0xffffffffffffffff},cbor.Token{kind:cbor.Kind.Negative,value:0xffffffffffffffff},cbor.Token{kind:cbor.Kind.Bool,boolean:true},cbor.Token{kind:cbor.Kind.Null},cbor.Token{kind:cbor.Kind.Undefined},cbor.Token{kind:cbor.Kind.Simple,value:255},cbor.Token{kind:cbor.Kind.Simple,value:19},cbor.Token{kind:cbor.Kind.Float,real:-1.5}]
 encoded = encode(arena,extremes[..])
 check(encoded.code == 0)
 state = cbor.reader(encoded.value)
 for expected in extremes {
  actual := next(&state)
  check(actual.found && actual.value.kind == expected.kind && actual.value.value == expected.value && actual.value.boolean == expected.boolean && actual.value.real == expected.real)
 }
 bad("\xff")
 bad("\x1f")
 bad("\xfc")
 bad("\xf8\x00")
 bad("\xbf\x01\xff")
 bad("\x9f\xc0\xff")
 bad("\x5f\x60\xff")
 bad("\x7f\x7f\xff\xff")
 bad("\x62\xc0\x80")
 bad("\x81")
 bad("\xc0")
 bad("\x9f")
 mark := mem.arena_mark(arena)
 invalid: [1]cbor.Token = [cbor.Token{kind:cbor.Kind.Tag,value:1}]
 check(encode(arena,invalid[..]).code == 1 && mem.arena_mark(arena) == mark)
 invalid[0] = cbor.Token{kind:cbor.Kind.Simple,value:24}
 check(encode(arena,invalid[..]).code == 1 && mem.arena_mark(arena) == mark)
 deep: [65]u8
 for i in 0..65 { deep[i] = 0x9f }
 state = cbor.reader(deep[..])
 for i in 0..64 { check(next(&state).found) }
 check(next(&state).code == 2)
 raw: [20]u8
 for tag in 0..256 {
  raw[0] = #cast(u8,tag)
  state = cbor.reader(raw[..])
  actual := next(&state)
  for actual.found { actual = next(&state) }
  check(actual.code == 0 || actual.code == 1)
 }
}
'''
with tempfile.TemporaryDirectory(prefix='dyn-cbor-') as directory:
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
print('PASS CBOR: RFC examples, all major types, indefinite structure, malformed input and cross-targets')
