#!/usr/bin/env python3
"""Production XIM callbacks: C ABI, locale decoding, owned order and bounds."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT = Path(__file__).resolve().parents[1]
DYN = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
ORACLE = r'''use "std/bytes" oracle_bytes
extern fn abi "dyn_xim_abi"(index: u32) usize
fn ime_check(ok: bool, message: []const u8) { if !ok { #panic(message) } }
fn ime_drain(host: *Window) { value := ordered.Event{}
  for next_event(host, &value) {} }
pub fn ime_oracle() {
  ime_check(#sizeof(XimText) == abi(0) && #offsetof(XimText, feedback) == abi(1) && #offsetof(XimText, string) == abi(2), "XIMText ABI")
  ime_check(#sizeof(PreeditDraw) == abi(3) && #offsetof(PreeditDraw, text) == abi(4), "XIM draw ABI")
  ime_check(#sizeof(PreeditCaret) == abi(5) && #sizeof(MbState) == abi(6) && #alignof(MbState) == abi(7), "XIM caret and locale state ABI")
  locale := "C.UTF-8\0"
  ime_check(set_locale(0, &locale[0]) != nil, "UTF8 test locale")
  host := Window{}
  host.events_enabled = true
  desktop := &host.desktop
  desktop.owner = &host
  desktop.text_input = true
  _ = preedit_start(nil, desktop, nil)
  wide: [3]u32 = [0x304b, 0x306a, 0x1f600]
  text := XimText{ length: 3, wide: 1, string: &wide[0] }
  draw := PreeditDraw{ caret: 2, text: &text }
  preedit_draw(nil, desktop, &draw)
  preedit_done(nil, desktop, nil)
  event := ordered.Event{}
  ime_check(next_event(&host, &event) && event.kind == ordered.Kind.Composition && event.text_length == 0, "start snapshot")
  ime_check(next_event(&host, &event) && oracle_bytes.equal(ordered.text(&event), "かな😀") && event.x == 6 && event.width == 1, "owned intermediate preedit")
  saved := ordered.composition(&event)
  ime_check(saved.text_length == 10 && saved.cursor_end == 6 && saved.active == 1, "portable composition decode")
  ime_check(next_event(&host, &event) && event.width == 0 && event.text_length == 0, "owned done snapshot")
  ime_check(saved.text[0] == 0xe3, "snapshot survives drain")
  // Declared character count is authoritative; the byte array has no NUL.
  multibyte: [5]u8 = ['h',0xc3,0xa9,'!', 'z']
  text = XimText{ length: 2, string: &multibyte[0] }
  draw = PreeditDraw{ caret: 2, text: &text }
  preedit_draw(nil, desktop, &draw)
  ime_check(oracle_bytes.equal(desktop.composition.text[..#cast(usize, desktop.composition.text_length)], "hé"), "locale character count")
  feedback := XimText{ length: 1 }
  draw = PreeditDraw{ caret: 2, change_length: 1, text: &feedback }
  preedit_draw(nil, desktop, &draw)
  ime_check(desktop.preedit_count == 2 && desktop.preedit[0] == 'h', "feedback does not erase text")
  caret := PreeditCaret{ position: 0, direction: 10, style: 1 }
  preedit_caret(nil, desktop, &caret)
  caret.direction = 0
  preedit_caret(nil, desktop, &caret)
  ime_check(caret.position == 1 && desktop.composition.cursor_begin == 1, "relative caret")
  caret.direction = 0
  preedit_caret(nil, desktop, &caret)
  ime_check(caret.position == 2 && desktop.composition.cursor_begin == 3, "caret maps Unicode bytes")
  caret.direction = 11
  caret.style = 0
  preedit_caret(nil, desktop, &caret)
  ime_check(desktop.composition.cursor_begin == -1, "invisible caret")
  ime_drain(&host)
  desktop.preedit_count = 128
  for i in 0..128 { desktop.preedit[i] = 'a' }
  wide[0] = 'x'
  wide[1] = 'y'
  text = XimText{ length: 2, wide: 1, string: &wide[0] }
  draw = PreeditDraw{ caret: 129, change_first: 127, text: &text }
  preedit_draw(nil, desktop, &draw)
  ime_check(desktop.preedit_count == 128 && desktop.preedit[127] == 'x', "bounded insert near end")
  ime_check(next_event(&host, &event) && event.kind == ordered.Kind.Overflow, "bounded insert reports loss")
  // An explicit disable also works without a native input context.
  set_text_input(&host, false, 0, 0, 0, 0)
  ime_check(!desktop.text_input && desktop.composition.active == 0 && desktop.composition_handled, "disable and final-poll ownership")
  ime_drain(&host)
  desktop.owns = true
  desktop.owned_length = 1
  desktop.owned[0] = 'a'
  request_paste(&host)
  desktop.owned[0] = 'b'
  request_paste(&host)
  desktop.received[0] = '!'
  ime_check(next_event(&host, &event) && event.kind == ordered.Kind.Clipboard && event.text[0] == 'a' && event.button == 1, "first owned reply")
  ime_check(next_event(&host, &event) && event.kind == ordered.Kind.Clipboard && event.text[0] == 'b' && event.button == 1, "second owned reply")
  desktop.paste_pending = true
  request_paste(&host)
  ime_check(next_event(&host, &event) && event.kind == ordered.Kind.Overflow && desktop.received[0] == '!', "overlap preserves pending reply")
}
'''
C = r'''#include <X11/Xlib.h>
#include <wchar.h>
#include <stddef.h>
size_t dyn_xim_abi(unsigned index) {
 const size_t values[]={sizeof(XIMText),offsetof(XIMText,feedback),offsetof(XIMText,string),sizeof(XIMPreeditDrawCallbackStruct),offsetof(XIMPreeditDrawCallbackStruct,text),sizeof(XIMPreeditCaretCallbackStruct),sizeof(mbstate_t),_Alignof(mbstate_t)};
 return index<sizeof(values)/sizeof(values[0]) ? values[index] : 0;
}
'''
if not sys.platform.startswith('linux') or not shutil.which('cc'):
    print('SKIP production XIM callback oracle: Linux and C headers required')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-xim-callback-') as directory:
    work=Path(directory)
    # The callback oracle is headless but its production module still links
    # Xlib/GL. Check optional development dependencies before compiling it.
    dependency=work/'dependencies.c'
    dependency.write_text('#include <X11/Xlib.h>\nint main(void) { return 0; }\n')
    available=subprocess.run(['cc',str(dependency),'-lX11','-lGL','-o',str(work/'dependencies')],capture_output=True)
    if available.returncode:
        print('SKIP production XIM callback oracle: X11/OpenGL development files unavailable')
        raise SystemExit(0)
    shutil.copytree(ROOT/'vendor/window/x11',work/'x11')
    (work/'x11/ime_oracle.dyn').write_text(ORACLE)
    (work/'main.dyn').write_text('use "./x11" x11\nfn main() { x11.ime_oracle() }\n')
    (work/'abi.c').write_text(C)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-c',str(work/'abi.c'),'-o',str(work/'abi.o')],check=True)
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'test'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--link',str(work/'abi.o'),'--output',str(output)],check=True,timeout=120)
        subprocess.run([str(output)],check=True,timeout=30)
print('PASS XIM production callbacks: ABI, nonterminated locale text, caret/feedback, bounded edits, owned composition/clipboard FIFO and disable')
