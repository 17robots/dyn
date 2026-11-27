#!/usr/bin/env python3
"""Revisioned UTF8 edits: atomic mutation, aliasing, snapshots and event assembly."""
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
SOURCE=r'''use edit "std/text/edit"
use mem "std/mem"
use bytes "std/bytes"
use events "vendor/window/events"
fn check(ok: bool, why: []const u8) { if !ok { #panic(why) } }
// A call's failure as a kind; Ok when it worked.
enum Kind { Ok, InvalidInput, Capacity, Stale }
struct Failure { kind: Kind }
fn failure_of(err: edit.EditErr) Failure {
  case err {
    .InvalidInput => { return Failure{ kind: Kind.InvalidInput } }
    .Capacity => { return Failure{ kind: Kind.Capacity } }
    .Stale => { return Failure{ kind: Kind.Stale } }
  }
}
fn broken(failure: Failure) bool { return failure.kind != Kind.Ok }
struct Snap { value: edit.Context, failure: Failure }
fn snapshot(tracker: *edit.Tracker, owner: u64, text: []const u8, cursor, anchor: usize, cause: edit.Cause) Snap {
  value := edit.snapshot(tracker, owner, text, cursor, anchor, cause) catch err { return Snap{ failure: failure_of(err) } }
  return Snap{ value: value }
}
fn apply(scratch: *mem.Arena, buffer: *edit.Buffer, replacement: *const edit.Replacement) Failure {
  edit.apply(scratch, buffer, replacement) catch err { return failure_of(err) }
  return Failure{}
}
struct Collected { value: edit.Replacement, ready: bool, failure: Failure }
fn collect(buffer: *events.EditBuffer, event: *const events.Event) Collected {
  result := events.collect_edit(buffer, event) catch { return Collected{ failure: Failure{ kind: Kind.InvalidInput } } }
  return Collected{ value: result.value, ready: result.ready }
}
fn main() {
  arena := mem.arena_alloc(0)
  defer mem.arena_release(arena)
  tracker := edit.Tracker{}
  first := snapshot(&tracker, 7, "hé world", 3, 3, edit.Cause.Other)
  again := snapshot(&tracker, 7, "hé world", 3, 3, edit.Cause.Other)
  check(!broken(first.failure) && again.value.token == first.value.token,"stable publication")
  storage: [64]u8
  _ = mem.copy(storage[..9],"hé world")
  buffer := edit.Buffer{storage:storage[..],length:9,cursor:3,anchor:3,token:first.value.token}
  replacement := edit.Replacement{start:3,end:9,text:"😀",token:first.value.token}
  mark := mem.arena_mark(arena)
  check(apply(arena,&buffer,&replacement).kind == Kind.Ok && buffer.length == 7 && buffer.cursor == 7 && buffer.anchor == 7 && buffer.token == 0,"atomic Unicode replacement")
  check(bytes.equal(storage[..7],"hé😀") && mem.arena_mark(arena)==mark,"bytes and scratch lifetime")
  check(apply(arena,&buffer,&replacement).kind == Kind.Stale && bytes.equal(storage[..7],"hé😀"),"replay rejected")
  next := snapshot(&tracker,7,storage[..7],7,7,edit.Cause.InputMethod)
  check(!broken(next.failure) && next.value.token != first.value.token && next.value.cause == edit.Cause.InputMethod,"changed context identity and cause")
  same := snapshot(&tracker,7,storage[..7],7,7,edit.Cause.Other)
  check(same.value.token == next.value.token && same.value.cause == edit.Cause.InputMethod,"unchanged cause is retained")
  buffer.token = next.value.token
  replacement = edit.Replacement{start:2,end:3,text:"x",token:buffer.token}
  check(apply(arena,&buffer,&replacement).kind == Kind.InvalidInput && buffer.length == 7 && buffer.token == next.value.token && bytes.equal(storage[..7],"hé😀"),"split codepoint rejected without mutation")
  replacement = edit.Replacement{start:0,end:0,text:"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",token:buffer.token}
  check(apply(arena,&buffer,&replacement).kind == Kind.Capacity && bytes.equal(storage[..7],"hé😀"),"capacity failure preserves bytes")
  _ = mem.copy(storage[..6],"abcdef")
  buffer = edit.Buffer{storage:storage[..],length:6,cursor:3,anchor:0,token:99}
  replacement = edit.Replacement{start:0,end:3,text:storage[..2],token:99}
  check(apply(arena,&buffer,&replacement).kind == Kind.Ok && bytes.equal(storage[..buffer.length],"abdef"),"aliased replacement")
  scratch_backing: [64 + mem.ArenaBufferOverhead]u8
  scratch := mem.arena_from_buffer(scratch_backing[..])
  scratch_bytes := scratch.data[mem.ArenaHeader..]
  _ = mem.copy(scratch_bytes[..6],"abcdef")
  scratch.poison_on_rewind = true
  buffer = edit.Buffer{storage:scratch_bytes[..16],length:6,cursor:0,anchor:0,token:99}
  replacement = edit.Replacement{start:0,end:1,text:"new",token:99}
  check(apply(scratch,&buffer,&replacement).kind == Kind.InvalidInput && mem.arena_used(scratch)==0 && bytes.equal(scratch_bytes[..6],"abcdef"),"pending scratch alias rejected")
  failed := snapshot(&tracker,7,"é",1,0,edit.Cause.Other)
  check(broken(failed.failure) && tracker.token == 0,"invalid publication invalidates old identity")
  back := snapshot(&tracker,7,"hé😀",7,7,edit.Cause.Other)
  check(back.value.token != next.value.token,"returning content never revives stale token")
  tracker.serial = 18446744073709551615
  failed = snapshot(&tracker,8,"new",0,0,edit.Cause.Other)
  check(failed.failure.kind == Kind.Stale && tracker.token == 0,"token exhaustion fails closed")
  collector := events.EditBuffer{}
  event := events.Event{kind:events.Kind.Edit,key:17,modifiers:2,x:0,y:3,width:260,text_length:256}
  for i in 0..256 { event.text[i] = 'x' }
  partial := collect(&collector,&event)
  check(!broken(partial.failure) && !partial.ready,"partial transaction")
  event.scancode = 256
  event.text_length = 4
  event.text[0] = 0xf0
  event.text[1] = 0x9f
  event.text[2] = 0x98
  event.text[3] = 0x80
  event.button = 1
  complete := collect(&collector,&event)
  event.text[0] = 'z'
  check(!broken(complete.failure) && complete.ready && complete.value.text.len==260 && complete.value.token == 8589934609 && complete.value.text[256] == 0xf0,"owned complete transaction")
  large: [512]u8
  _ = mem.copy(large[..3],"old")
  buffer = edit.Buffer{storage:large[..],length:3,cursor:3,anchor:3,token:complete.value.token}
  check(apply(arena,&buffer,&complete.value).kind == Kind.Ok && buffer.length==260 && large[259]==0x80,"assembled transaction applies")
  event = events.Event{kind:events.Kind.Edit,key:1,width:2,text_length:1}
  event.text[0] = 'a'
  check(!broken(collect(&collector,&event).failure),"new transaction")
  event.kind = events.Kind.Overflow
  check(broken(collect(&collector,&event).failure) && !collector.active,"overflow discards partial edit")
  event = events.Event{kind:events.Kind.Edit,key:1,width:2,scancode:1,text_length:1,button:1}
  event.text[0] = 'b'
  check(broken(collect(&collector,&event).failure),"orphan final rejected")
  golden(arena)
}
'''
def literal(data):
    return '"'+''.join(f'\\x{b:02x}' for b in data)+'"'
rng=random.Random(948135)
GOLDEN='fn golden(arena: *mem.Arena) {\n'
for _ in range(64):
    chars=[rng.choice(['a','é','水','😀',' ','x']) for _ in range(rng.randrange(0,14))]
    low=rng.randrange(len(chars)+1);high=rng.randrange(low,len(chars)+1)
    incoming=''.join(rng.choice(['Z','ü','界','🙂']) for _ in range(rng.randrange(0,8))).encode()
    original=''.join(chars).encode();start=len(''.join(chars[:low]).encode());end=len(''.join(chars[:high]).encode())
    expected=original[:start]+incoming+original[end:]
    GOLDEN+=' if true { storage: [128]u8\n'
    GOLDEN+=f' _ = mem.copy(storage[..{len(original)}],{literal(original)})\n'
    GOLDEN+=f' buffer := edit.Buffer{{storage:storage[..],length:{len(original)},cursor:{start},anchor:{end},token:37}}\n'
    GOLDEN+=f' replacement := edit.Replacement{{start:{start},end:{end},text:{literal(incoming)},token:37}}\n'
    GOLDEN+=f' check(apply(arena,&buffer,&replacement).kind == Kind.Ok && bytes.equal(storage[..buffer.length],{literal(expected)}) && buffer.cursor=={start+len(incoming)},"Python independent slice oracle")\n }}\n'
GOLDEN+='}\n'
# Host qualification fixture includes the independent generated vectors.
SOURCE+=GOLDEN
with tempfile.TemporaryDirectory(prefix='dyn-text-edit-') as directory:
    work=Path(directory)
    (work/'main.dyn').write_text(SOURCE,encoding='utf-8')
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'test'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--output',str(output)],check=True,timeout=300)
        subprocess.run([str(output)],check=True,timeout=90)
    for target in ('aarch64-linux','riscv64-linux','x86_64-macos','aarch64-macos','x86_64-windows','aarch64-windows','wasm32-wasi'):
        output=work/target
        subprocess.run([DYN,'build',str(work),'--release','--target',target,'--quiet','--output',str(output)],check=True,timeout=300)
        emulator={'aarch64-linux':'qemu-aarch64','riscv64-linux':'qemu-riscv64','x86_64-windows':'wine'}.get(target)
        if emulator and shutil.which(emulator): subprocess.run([emulator,str(output)],check=True,timeout=120)
print('PASS revisioned text edits: 64 Python goldens, Unicode/alias/capacity atomicity, stale tokens, context ownership and chunk assembly (debug/O2/O3 and cross-targets)')
