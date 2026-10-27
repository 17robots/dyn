#!/usr/bin/env python3
"""XIM surrounding publication fails explicitly without mutating current input."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
ORACLE=r'''fn surround_check(ok: bool, reason: []const u8) { if !ok { #panic(reason) } }
pub fn surround_oracle() {
  host := Window{}
  result := set_surrounding_text(&host,"text",4,4,1)
  surround_check(!result.ok && result.kind == errors.Kind.InvalidState,"closed window")
  // Sentinel native handles intentionally cannot be called. This backend
  // must not attempt to register an unqualified string-conversion callback.
  host.display = #cast(rawptr,1)
  host.handle = 1
  host.desktop.context = #cast(rawptr,2)
  host.desktop.method = #cast(rawptr,3)
  host.desktop.owner = &host
  host.desktop.text_input = true
  host.desktop.style = 0x402
  host.desktop.preedit_count = 2
  host.desktop.preedit[0] = 'a'
  host.desktop.preedit[1] = 'b'
  host.desktop.composition.active = 1
  host.desktop.composition.text_length = 2
  host.desktop.composition.text[0] = 'a'
  host.desktop.composition.text[1] = 'b'
  host.desktop.text_length = 1
  host.desktop.text[0] = 'x'
  result = set_surrounding_text(&host,"text",4,4,1)
  surround_check(!result.ok && result.kind == errors.Kind.InvalidState,"ordered consumer required")
  host.events_enabled = true
  ordered_push(&host,ordered.Event{kind:ordered.Kind.Wake,x:37})
  result = set_surrounding_text(&host,"hé😀",3,7,0x100000001)
  surround_check(!result.ok && result.kind == errors.Kind.Unsupported,"valid publication unsupported")
  result = set_surrounding_text(&host,"",0,0,1)
  surround_check(!result.ok && result.kind == errors.Kind.Unsupported,"empty valid context unsupported")
  result = set_surrounding_text(&host,"abc",4,0,1)
  surround_check(!result.ok && result.kind == errors.Kind.InvalidInput,"cursor range")
  result = set_surrounding_text(&host,"abc",0,4,1)
  surround_check(!result.ok && result.kind == errors.Kind.InvalidInput,"anchor range")
  result = set_surrounding_text(&host,"hé",2,0,1)
  surround_check(!result.ok && result.kind == errors.Kind.InvalidInput,"cursor boundary")
  result = set_surrounding_text(&host,"hé",0,2,1)
  surround_check(!result.ok && result.kind == errors.Kind.InvalidInput,"anchor boundary")
  result = set_surrounding_text(&host,"\xff",0,0,1)
  surround_check(!result.ok && result.kind == errors.Kind.InvalidInput,"invalid UTF8")
  result = set_surrounding_text(&host,"a\0b",0,0,1)
  surround_check(!result.ok && result.kind == errors.Kind.InvalidInput,"native string NUL")
  result = set_surrounding_text(&host,"abc",0,0,0)
  surround_check(!result.ok && result.kind == errors.Kind.InvalidInput,"zero revision")
  large: [4097]u8 = []
  for i in 0..#len(large) { large[i] = 'a' }
  result = set_surrounding_text(&host,large[..],0,0,1)
  surround_check(!result.ok && result.kind == errors.Kind.Capacity,"context byte cap")
  result = set_surrounding_text(&host,large[..4096],4096,0,1)
  surround_check(!result.ok && result.kind == errors.Kind.Unsupported,"maximum valid context")
  surround_check(host.desktop.context == #cast(rawptr,2) && host.desktop.method == #cast(rawptr,3) && host.desktop.text_input && host.desktop.style == 0x402,"focus and method unchanged")
  surround_check(host.desktop.preedit_count == 2 && host.desktop.preedit[0] == 'a' && host.desktop.preedit[1] == 'b' && host.desktop.composition.active == 1 && host.desktop.composition.text_length == 2 && host.desktop.composition.text[1] == 'b',"preedit unchanged")
  surround_check(host.desktop.text_length == 1 && host.desktop.text[0] == 'x',"legacy commit unchanged")
  event := ordered.Event{}
  surround_check(next_event(&host,&event) && event.kind == ordered.Kind.Wake && event.x == 37,"queued input unchanged")
  surround_check(!next_event(&host,&event),"no conversion or overflow falsely emitted")
}
'''
if not sys.platform.startswith('linux') or not shutil.which('cc'):
    print('SKIP XIM surrounding boundary: Linux development libraries required')
    raise SystemExit(0)
with tempfile.TemporaryDirectory(prefix='dyn-xim-surround-') as directory:
    work=Path(directory)
    dependency=work/'dependency.c'
    dependency.write_text('#include <X11/Xlib.h>\nint main(void) { return 0; }\n')
    available=subprocess.run(['cc',str(dependency),'-lX11','-lGL','-o',str(work/'dependency')],capture_output=True)
    if available.returncode:
        print('SKIP XIM surrounding boundary: X11/OpenGL development libraries required')
        raise SystemExit(0)
    shutil.copytree(ROOT/'vendor/window/x11',work/'x11')
    (work/'x11/surround_oracle.dyn').write_text(ORACLE,encoding='utf-8')
    (work/'main.dyn').write_text('use "./x11" x11\nfn main() { x11.surround_oracle() }\n')
    for flags in (['--debug'],['--release'],['--release','--opt-level','3']):
        output=work/'test'
        subprocess.run([DYN,'build',str(work),*flags,'--quiet','--output',str(output)],check=True,timeout=120)
        subprocess.run([str(output)],check=True,timeout=30)
    for target in ('aarch64-linux','riscv64-linux'):
        subprocess.run([DYN,'build',str(work),'--release','--target',target,'--emit-object','--no-link','--quiet','--output',str(work/target)],check=True,timeout=120)
print('PASS XIM surrounding boundary: validation, explicit Unsupported, no input-method registration or input mutation (debug/O2/O3 and Linux object targets)')
