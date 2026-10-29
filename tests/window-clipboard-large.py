#!/usr/bin/env python3
"""Real X11 large clipboard snapshots and ICCCM INCR transfers."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
ORACLE=r'''#target(kernel: linux)
pub fn clipboard_inject_wake(reader: *Window) { ordered_push(reader, ordered.Event{kind:ordered.Kind.Wake}) }
pub fn clipboard_inject(reader: *Window, kind: usize, format: i32, data: *const u8, count: i32, notify: bool) {
 _ = change_property(reader.display,reader.handle,reader.desktop.property_atom,kind,format,0,data,count)
 if notify {
  reply := SelectionNotify{kind:31,display:reader.display,requestor:reader.handle,selection:reader.desktop.clipboard_atom,target:reader.desktop.utf8_atom,property:reader.desktop.property_atom}
  _ = send_event(reader.display,reader.handle,0,0,&reply)
 }
 _ = sync(reader.display,0)
 if !poll(reader).ok { #panic("clipboard injection poll") }
}
'''
SOURCE=r'''use "probe" window
use "vendor/window/events" events
use "std/mem" mem
use "std/bytes" bytes
use "std/errors" errors
checks: usize
extern fn report "printf"(format: *const u8, ...) i32
extern fn flush "fflush"(stream: rawptr) i32
fn check(ok: bool, case_id: usize) { checks += 1
 if !ok { format := "failed clipboard check %llu (case %llu)\n\x00"
   _ = report(&format[0],#cast(u64,checks),#cast(u64,case_id))
   _ = flush(nil)
   #panic("large X11 clipboard") } }
fn complete(owner, reader: *window.Window) {
  for i in 0..5000 {
    check(window.poll(owner).ok && window.poll(reader).ok,16)
    if !window.paste_pending(reader) { check(window.paste_status(reader).ok,17)
      return }
    window.wait(reader, 1)
  }
  #panic("X11 clipboard transfer timed out")
}
fn main() {
 owner := window.Window{}
 reader := window.Window{}
 check(window.open(&owner,"clipboard owner",80,80).ok,26)
 defer { window.close(&owner) }
 check(window.open(&reader,"clipboard reader",80,80).ok,28)
 defer { window.close(&reader) }
 arena := mem.arena_create(0)
 defer { mem.arena_release(arena) }
 large := mem.push_bytes_uninit(arena, 1200000)
 for i in 0..#len(large) { large[i] = #cast(u8, 32 + i % 90) }
 check(window.try_set_clipboard(&owner,large).ok,34)
 window.request_paste(&owner)
 check(!window.paste_pending(&owner) && window.paste_status(&owner).ok && bytes.equal(window.clipboard(&owner),large),36)
 window.listen_events(&reader,true)
 // Discard window-creation events before testing reply queue atomicity.
 _ = window.poll(&reader)
 event := events.Event{}
 for window.next_event(&reader,&event) {}
 window.request_paste(&reader)
 check(window.paste_pending(&reader),43)
 check(window.poll(&owner).ok,44)
 // A new offer and SelectionClear cannot alter the outgoing INCR snapshot.
 check(window.try_set_clipboard(&owner,"new offer").ok,46)
 check(window.try_set_clipboard(&reader,"take ownership").ok,47)
 complete(&owner,&reader)
 check(bytes.equal(window.clipboard(&reader),large),49)
 clipboard_count: usize = 0
 overflow_count: usize = 0
 for window.next_event(&reader,&event) {
   if event.kind == events.Kind.Clipboard { clipboard_count += 1 }
   if event.kind == events.Kind.Overflow { overflow_count += 1 }
 }
 check(clipboard_count == 0 && overflow_count == 1,56)
 // Snapshot-only request retains unrelated input and never queues payload
 // chunks or overflow merely because the successful snapshot is large.
 check(window.try_set_clipboard(&owner,large).ok,1007)
 window.clipboard_inject_wake(&reader)
 window.request_paste_snapshot(&reader)
 // A concurrent request cannot change the pending snapshot's delivery mode.
 window.request_paste(&reader)
 // Busy request reports misuse; drain that notification before completion.
 for window.next_event(&reader,&event) {}
 window.clipboard_inject_wake(&reader)
 complete(&owner,&reader)
 check(bytes.equal(window.clipboard(&reader),large),1008)
 found_wake := false
 for window.next_event(&reader,&event) {
   check(event.kind!=events.Kind.Clipboard && event.kind!=events.Kind.Overflow,1009)
   if event.kind==events.Kind.Wake { found_wake=true }
 }
 check(found_wake,1010)
 check(window.try_set_clipboard(&owner,"new offer").ok,57)
 // Rejection leaves current offer unchanged.
 oversized := mem.push_bytes_uninit(arena,16777217)
 check(window.try_set_clipboard(&owner,oversized).kind==errors.Kind.Capacity,60)
 window.request_paste(&reader)
 complete(&owner,&reader)
 check(bytes.equal(window.clipboard(&reader),"new offer"),63)
 for window.next_event(&reader,&event) {}
 check(window.try_set_clipboard(&owner,"").ok,65)
 window.request_paste(&reader)
 complete(&owner,&reader)
 check(#len(window.clipboard(&reader))==0,68)
 found := false
 for window.next_event(&reader,&event) {
   if event.kind==events.Kind.Clipboard { check(event.text_length==0 && event.width==0 && event.button==1,71)
     found=true }
 }
 check(found,74)
 check(window.try_set_clipboard(&owner,"h\xc3\xa9\xf0\x9f\x98\x80").ok,75)
 window.request_paste(&reader)
 complete(&owner,&reader)
 check(bytes.equal(window.clipboard(&reader),"h\xc3\xa9\xf0\x9f\x98\x80"),78)
 // Malformed external UTF8/NUL and oversized INCR announcements fail without
 // publishing partial bytes or replacing the previous completed snapshot.
 invalid: [2]u8 = [0xc0,0x80]
 for mode in 0..3 {
   window.request_paste(&reader)
   if mode==0 { window.clipboard_inject(&reader,reader.desktop.utf8_atom,8,&invalid[0],2,true) }
   else if mode==1 { invalid[0]=0
     window.clipboard_inject(&reader,reader.desktop.utf8_atom,8,&invalid[0],1,true) }
   else {
     hint: usize = 16777217
     window.clipboard_inject(&reader,reader.desktop.incr_atom,32,#cast(*const u8,&hint),1,true)
     check(window.paste_pending(&reader),1001)
     window.clipboard_inject(&reader,reader.desktop.utf8_atom,8,nil,0,false)
   }
   check(!window.paste_pending(&reader) && !window.paste_status(&reader).ok,1002)
   check(bytes.equal(window.clipboard(&reader),"h\xc3\xa9\xf0\x9f\x98\x80"),1003)
   check(window.poll(&owner).ok && window.poll(&reader).ok,1004)
   for window.next_event(&reader,&event) {}
 }
 check(window.try_set_clipboard(&owner,"bad\0text").kind==errors.Kind.InvalidInput,1005)
 check(window.try_set_clipboard(&owner,"\xc0\x80").kind==errors.Kind.InvalidInput,1006)
 // Destroy a requestor after INCR starts. Sender cleanup must not raise a
 // fatal asynchronous BadWindow error or retain its copied snapshot.
 check(window.try_set_clipboard(&owner,large).ok,84)
 window.request_paste(&reader)
 check(window.poll(&owner).ok,86)
 window.close(&reader)
 for i in 0..10 { check(window.poll(&owner).ok,88) }
 for i in 0..4 { check(owner.desktop.outgoing[i].requestor==0,89) }
 check(window.open(&reader,"clipboard reader 2",80,80).ok,90)
 window.request_paste(&reader)
 check(window.poll(&owner).ok,92)
 check(window.poll(&reader).ok,93)
 // Destroy the owner during an incremental reply. Preserve the last completed
 // snapshot and complete the request with an explicit failure.
 window.close(&owner)
 for i in 0..1000 {
   check(window.poll(&reader).ok,101)
   if !window.paste_pending(&reader) { break }
   window.wait(&reader,1)
 }
 check(!window.paste_pending(&reader) && window.paste_status(&reader).kind==errors.Kind.System,105)
}
'''
if not os.environ.get('DISPLAY'):
    print('SKIP large X11 clipboard: DISPLAY unavailable')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-clipboard-large-') as directory:
    work=Path(directory);(work/'main.dyn').write_text(SOURCE)
    shutil.copytree(ROOT/'vendor/window/x11',work/'probe')
    (work/'probe/oracle.dyn').write_text(ORACLE)
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'runner'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--output',str(output)],check=True,timeout=180)
        subprocess.run([str(output)],check=True,timeout=60)
    for target in ('aarch64-linux','riscv64-linux'):
        subprocess.run([DYN,'build',str(work),'--release','--target',target,'--emit-object','--no-link','--quiet','--output',str(work/(target+'.o'))],check=True,timeout=180)
print('PASS X11 clipboard: 1.2 MB self/cross-window INCR snapshots, in-flight ownership, atomic ordered overflow, snapshot-only delivery, capacity/UTF8 rejection, empty replies and peer destruction (debug/O2/O3)')
