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
SOURCE=r'''use "std/text/edit" edit
use "std/mem" mem
use "std/bytes" bytes
use "std/errors" errors
use "vendor/window/events" events
fn check(ok: bool, why: []const u8) { if !ok { #panic(why) } }
fn main() {
  arena := mem.arena_create(0)
  defer mem.arena_release(arena)
  tracker := edit.Tracker{}
  first := edit.snapshot(&tracker, 7, "hé world", 3, 3, edit.Cause.Other)
  again := edit.snapshot(&tracker, 7, "hé world", 3, 3, edit.Cause.Other)
  check(first.ok && again.value.token == first.value.token,"stable publication")
  storage: [64]u8 = []
  _ = mem.copy(storage[..9],"hé world")
  buffer := edit.Buffer{storage:storage[..],length:9,cursor:3,anchor:3,token:first.value.token}
  replacement := edit.Replacement{start:3,end:9,text:"😀",token:first.value.token}
  mark := mem.arena_mark(arena)
  check(edit.apply(arena,&buffer,&replacement).ok && buffer.length == 7 && buffer.cursor == 7 && buffer.anchor == 7 && buffer.token == 0,"atomic Unicode replacement")
  check(bytes.equal(storage[..7],"hé😀") && mem.arena_mark(arena)==mark,"bytes and scratch lifetime")
  check(edit.apply(arena,&buffer,&replacement).kind == errors.Kind.InvalidState && bytes.equal(storage[..7],"hé😀"),"replay rejected")
  next := edit.snapshot(&tracker,7,storage[..7],7,7,edit.Cause.InputMethod)
  check(next.ok && next.value.token != first.value.token && next.value.cause == edit.Cause.InputMethod,"changed context identity and cause")
  same := edit.snapshot(&tracker,7,storage[..7],7,7,edit.Cause.Other)
  check(same.value.token == next.value.token && same.value.cause == edit.Cause.InputMethod,"unchanged cause is retained")
  buffer.token = next.value.token
  replacement = edit.Replacement{start:2,end:3,text:"x",token:buffer.token}
  check(edit.apply(arena,&buffer,&replacement).kind == errors.Kind.InvalidInput && buffer.length == 7 && buffer.token == next.value.token && bytes.equal(storage[..7],"hé😀"),"split codepoint rejected without mutation")
  replacement = edit.Replacement{start:0,end:0,text:"xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",token:buffer.token}
  check(edit.apply(arena,&buffer,&replacement).kind == errors.Kind.Capacity && bytes.equal(storage[..7],"hé😀"),"capacity failure preserves bytes")
  _ = mem.copy(storage[..6],"abcdef")
  buffer = edit.Buffer{storage:storage[..],length:6,cursor:3,anchor:0,token:99}
  replacement = edit.Replacement{start:0,end:3,text:storage[..2],token:99}
  check(edit.apply(arena,&buffer,&replacement).ok && bytes.equal(storage[..buffer.length],"abdef"),"aliased replacement")
  scratch_backing: [64 + mem.ArenaBufferOverhead]u8 = []
  scratch := mem.arena_from_buffer(scratch_backing[..])
  scratch_bytes := scratch.data[mem.ArenaHeader..]
  _ = mem.copy(scratch_bytes[..6],"abcdef")
  scratch.poison_on_rewind = true
  buffer = edit.Buffer{storage:scratch_bytes[..16],length:6,cursor:0,anchor:0,token:99}
  replacement = edit.Replacement{start:0,end:1,text:"new",token:99}
  check(edit.apply(scratch,&buffer,&replacement).kind == errors.Kind.InvalidInput && mem.arena_used(scratch)==0 && bytes.equal(scratch_bytes[..6],"abcdef"),"pending scratch alias rejected")
  failed := edit.snapshot(&tracker,7,"é",1,0,edit.Cause.Other)
  check(!failed.ok && tracker.token == 0,"invalid publication invalidates old identity")
  back := edit.snapshot(&tracker,7,"hé😀",7,7,edit.Cause.Other)
  check(back.value.token != next.value.token,"returning content never revives stale token")
  tracker.serial = 18446744073709551615
  failed = edit.snapshot(&tracker,8,"new",0,0,edit.Cause.Other)
  check(failed.kind == errors.Kind.Overflow && tracker.token == 0,"token exhaustion fails closed")
  collector := events.EditBuffer{}
  event := events.Event{kind:events.Kind.Edit,key:17,modifiers:2,x:0,y:3,width:260,text_length:256}
  for i in 0..256 { event.text[i] = 'x' }
  partial := events.collect_edit(&collector,&event)
  check(partial.ok && !partial.ready,"partial transaction")
  event.scancode = 256
  event.text_length = 4
  event.text[0] = 0xf0
  event.text[1] = 0x9f
  event.text[2] = 0x98
  event.text[3] = 0x80
  event.button = 1
  complete := events.collect_edit(&collector,&event)
  event.text[0] = 'z'
  check(complete.ok && complete.ready && #len(complete.value.text)==260 && complete.value.token == 8589934609 && complete.value.text[256] == 0xf0,"owned complete transaction")
  large: [512]u8 = []
  _ = mem.copy(large[..3],"old")
  buffer = edit.Buffer{storage:large[..],length:3,cursor:3,anchor:3,token:complete.value.token}
  check(edit.apply(arena,&buffer,&complete.value).ok && buffer.length==260 && large[259]==0x80,"assembled transaction applies")
  event = events.Event{kind:events.Kind.Edit,key:1,width:2,text_length:1}
  event.text[0] = 'a'
  check(events.collect_edit(&collector,&event).ok,"new transaction")
  event.kind = events.Kind.Overflow
  check(!events.collect_edit(&collector,&event).ok && !collector.active,"overflow discards partial edit")
  event = events.Event{kind:events.Kind.Edit,key:1,width:2,scancode:1,text_length:1,button:1}
  event.text[0] = 'b'
  check(!events.collect_edit(&collector,&event).ok,"orphan final rejected")
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
    GOLDEN+=' if true { storage: [128]u8 = []\n'
    GOLDEN+=f' _ = mem.copy(storage[..{len(original)}],{literal(original)})\n'
    GOLDEN+=f' buffer := edit.Buffer{{storage:storage[..],length:{len(original)},cursor:{start},anchor:{end},token:37}}\n'
    GOLDEN+=f' replacement := edit.Replacement{{start:{start},end:{end},text:{literal(incoming)},token:37}}\n'
    GOLDEN+=f' check(edit.apply(arena,&buffer,&replacement).ok && bytes.equal(storage[..buffer.length],{literal(expected)}) && buffer.cursor=={start+len(incoming)},"Python independent slice oracle")\n }}\n'
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
