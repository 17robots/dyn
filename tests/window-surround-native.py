#!/usr/bin/env python3
"""Native surrounding snapshots and atomic correction transactions."""
import ast
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'vendor/window/native'
COMMON=r'''#include "desktop_common.h"
#include <assert.h>
#include <stddef.h>
#include <stdio.h>
static Desktop desktop;
int main(void) {
 assert(sizeof(dyn_window_event)==312);
 const uint8_t original[]={'a',0xc3,0xa9,0xf0,0x9f,0x98,0x80,'z'};
 assert(!desktop_surrounding(&desktop,original,sizeof(original),7,3,1));
 desktop_listen(&desktop,1);
 assert(desktop_surrounding(&desktop,original,sizeof(original),7,3,0x1122334455667788ULL)==1);
 Surrounding saved=desktop.surrounding;
 assert(!desktop_surrounding(&desktop,original,sizeof(original),2,3,2));
 assert(!memcmp(&saved,&desktop.surrounding,sizeof(saved)));
 const uint8_t invalid[]={0xc0,0x80};
 assert(!desktop_surrounding(&desktop,invalid,sizeof(invalid),0,0,2));
 const uint8_t nul[]={'a',0,'z'};
 assert(!desktop_surrounding(&desktop,nul,sizeof(nul),0,0,2));
 assert(!desktop_surrounding(&desktop,original,sizeof(original),7,3,0));
 assert(desktop_surrounding(&desktop,original,4097,0,0,2)==-2);
 assert(!memcmp(&saved,&desktop.surrounding,sizeof(saved)));
 assert(!desktop_surrounding(&desktop,(const uint8_t*)"different",9,0,0,saved.token));
 assert(desktop_surrounding(&desktop,original,sizeof(original),7,3,saved.token)==1);
 assert(surrounding_utf16(original,7)==4);
 uint32_t offset=0;
 assert(surrounding_byte(original,sizeof(original),4,&offset)&&offset==7);
 assert(!surrounding_byte(original,sizeof(original),3,&offset));
 assert(!desktop_edit(&desktop,&saved,2,7,(const uint8_t*)"x",1));
 dyn_window_event event; assert(desktop_next(&desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW);
 assert(!desktop_edit(&desktop,&saved,1,8,nul,sizeof(nul)));
 assert(desktop.consumed_token==0&&!memcmp(&saved,&desktop.surrounding,sizeof(saved)));
 assert(desktop_next(&desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW);
 uint8_t replacement[600];memset(replacement,'r',sizeof(replacement));
 memcpy(replacement+255,"\xf0\x9f\x98\x80",4);
 for(unsigned i=0;i<127;i++)desktop_simple(&desktop,DYN_EVENT_WAKE);
 assert(!desktop_edit(&desktop,&saved,1,8,replacement,sizeof(replacement)));
 assert(desktop.event_count==127&&desktop.event_dropped==3);
 for(unsigned i=0;i<127;i++)assert(desktop_next(&desktop,&event)&&event.kind==DYN_EVENT_WAKE);
 assert(desktop_next(&desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW&&event.dropped==3);
 assert(desktop_edit(&desktop,&saved,1,8,replacement,sizeof(replacement)));
 memset(replacement,'!',sizeof(replacement));
 unsigned used=0, chunks=0;
 while(desktop_next(&desktop,&event)) {
  assert(event.kind==DYN_EVENT_EDIT&&event.key==0x55667788&&event.modifiers==0x11223344);
  assert(event.x==1&&event.y==8&&event.width==600&&event.scancode==used);
  if(chunks==0)assert(event.text_length==255&&event.text[0]=='r'&&!event.button);
  if(chunks==1)assert(event.text_length==256&&event.text[0]==0xf0&&!event.button);
  if(chunks==2)assert(event.text_length==89&&event.button);
  used+=event.text_length;chunks++;
 }
 assert(used==600&&chunks==3&&desktop.consumed_token==saved.token);
 assert(!desktop_surrounding(&desktop,original,sizeof(original),7,3,saved.token));
 assert(!desktop_edit(&desktop,&saved,1,8,(const uint8_t*)"replay",6));
 assert(desktop_next(&desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW);
 assert(desktop_surrounding(&desktop,original,sizeof(original),7,3,2)==1);
 saved=desktop.surrounding;
 assert(desktop_edit(&desktop,&saved,3,7,NULL,0));
 assert(desktop_next(&desktop,&event)&&event.kind==DYN_EVENT_EDIT&&event.text_length==0&&event.width==0&&event.button);
 puts("PASS native surrounding validation, UTF16 boundaries, owned atomic edits, token replay rejection and overflow");
}
'''
WAYLAND_MAIN=r'''int main(void) {
 Host h={0};h.scale=2;h.surface=(struct wl_surface*)(uintptr_t)1;
 h.text_input=(struct zwp_text_input_v3*)(uintptr_t)1;
 desktop_listen(&h.desktop,1);
 const uint8_t original[]={'a',0xc3,0xa9,0xf0,0x9f,0x98,0x80,'z'};
 assert(dyn_window_set_surrounding_text(&h,original,sizeof(original),7,3,10,0)==1);
 assert(surround_calls==0&&h.text_serial==0);
 text_enter(&h,NULL,h.surface);
 dyn_window_set_text_input(&h,1,10,20,1,16);
 assert(cause_value==ZWP_TEXT_INPUT_V3_CHANGE_CAUSE_OTHER);
 assert(enables==1&&surround_calls==1&&wire_cursor==7&&wire_anchor==3&&!memcmp(wire_text,original,sizeof(original)));
 uint32_t serial=h.text_serial;
 text_delete(&h,NULL,2,1);text_commit(&h,NULL,"X");text_done(&h,NULL,serial);
 dyn_window_event event;
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_EDIT&&event.key==10&&event.x==1&&event.y==8&&event.text_length==1&&event.text[0]=='X');
 assert(!desktop_next(&h.desktop,&event)&&!h.desktop.pending.text_length);
 text_delete(&h,NULL,2,1);text_commit(&h,NULL,"again");text_done(&h,NULL,serial);
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW);
 assert(!dyn_window_set_surrounding_text(&h,original,sizeof(original),7,3,10,0));
 assert(dyn_window_set_surrounding_text(&h,original,sizeof(original),7,3,11,0)==1);
 assert(cause_value==ZWP_TEXT_INPUT_V3_CHANGE_CAUSE_OTHER);
 uint32_t next=h.text_serial;
 text_delete(&h,NULL,0,0);text_commit(&h,NULL,"bad");text_done(&h,NULL,serial);
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW);
 text_delete(&h,NULL,1,0);text_commit(&h,NULL,"bad");text_done(&h,NULL,next);
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW);
 assert(dyn_window_set_surrounding_text(&h,original,sizeof(original),7,3,12,1)==1);
 assert(cause_value==ZWP_TEXT_INPUT_V3_CHANGE_CAUSE_INPUT_METHOD);
 text_commit(&h,NULL,"selection");text_done(&h,NULL,h.text_serial);
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_EDIT&&event.x==3&&event.y==7&&event.key==12);
 assert(dyn_window_set_surrounding_text(&h,(const uint8_t*)"abc",3,3,3,13,0)==1);
 text_commit(&h,NULL,"plain");text_done(&h,NULL,h.text_serial);
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_TEXT&&event.text_length==5);
 char large[601];memset(large,'x',600);large[600]=0;
 for(unsigned i=0;i<127;i++)desktop_simple(&h.desktop,DYN_EVENT_WAKE);
 text_delete(&h,NULL,0,0);text_commit(&h,NULL,large);text_done(&h,NULL,h.text_serial);
 assert(h.desktop.event_count==127&&h.desktop.event_dropped==3);
 drain(&h);
 assert(dyn_window_set_surrounding_text(&h,original,4001,0,0,99,0)==-2);
 assert(h.desktop.surrounding.token==13);
 assert(dyn_window_set_surrounding_text(&h,original,sizeof(original),2,3,99,0)==0);
 assert(h.desktop.surrounding.token==13);
 assert(dyn_window_set_surrounding_text(&h,original,sizeof(original),7,3,99,2)==0);
 uint32_t retired=h.text_serial;
 for(unsigned i=0;i<17;i++)dyn_window_set_text_input(&h,1,(int32_t)i,20,1,16);
 text_delete(&h,NULL,0,0);text_commit(&h,NULL,"old");text_done(&h,NULL,retired);
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW);
 dyn_window_set_text_input(&h,0,0,0,0,0);
 assert(h.desktop.consumed_token==13);
 puts("PASS production Wayland surrounding publication, UTF8 selection/delete/commit, source revisions, cause, retired serials and atomic overflow");
}
'''
COCOA=r'''#include "cocoa.m"
#include <objc/runtime.h>
#include <assert.h>
#include <stdio.h>
@interface SurroundProbe : NSObject
@property(nonatomic, assign) Host *host;
@end
@implementation SurroundProbe
@end
int main(void) { @autoreleasepool {
 Host h={0}; desktop_listen(&h.desktop,1);
 assert(desktop_surrounding(&h.desktop,(const uint8_t *)"original",8,8,0,123)==1);
 Surrounding saved=h.desktop.surrounding;
 SurroundProbe *probe=[SurroundProbe new]; probe.host=&h;
 unichar units[]={'A',0,'B'};
 NSString *value=[[NSString alloc] initWithCharacters:units length:3];
 assert([value lengthOfBytesUsingEncoding:NSUTF8StringEncoding]==3);
 void (*insert)(id,SEL,id,NSRange)=(void *)class_getMethodImplementation([DynTextView class],@selector(insertText:replacementRange:));
 insert(probe,@selector(insertText:replacementRange:),value,NSMakeRange(0,8));
 dyn_window_event event;
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW);
 assert(!desktop_next(&h.desktop,&event)&&!h.desktop.consumed_token&&!memcmp(&saved,&h.desktop.surrounding,sizeof(saved)));
 void (*marked)(id,SEL,id,NSRange,NSRange)=(void *)class_getMethodImplementation([DynTextView class],@selector(setMarkedText:selectedRange:replacementRange:));
 marked(probe,@selector(setMarkedText:selectedRange:replacementRange:),value,NSMakeRange(0,0),NSMakeRange(0,8));
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW);
 assert(!h.marked_text&&!h.desktop.consumed_token&&!memcmp(&saved,&h.desktop.surrounding,sizeof(saved)));
 /* Ordinary commits reject the entire string as well. */
 assert(desktop_surrounding(&h.desktop,(const uint8_t *)"original",8,8,8,124)==1);
 insert(probe,@selector(insertText:replacementRange:),value,NSMakeRange(NSNotFound,0));
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW);
 assert(!desktop_next(&h.desktop,&event)&&!h.desktop.pending.text_length);
 puts("PASS Cocoa production callbacks reject embedded NUL without partial text or context mutation");
 } return 0; }
'''
EXTRA=r'''static unsigned surround_calls,cause_value;
static int32_t wire_cursor,wire_anchor;static char wire_text[4001];
static void mock_surround(struct zwp_text_input_v3*t,const char*s,int32_t cursor,int32_t anchor){(void)t;surround_calls++;strcpy(wire_text,s);wire_cursor=cursor;wire_anchor=anchor;}
static void mock_cause(struct zwp_text_input_v3*t,uint32_t value){(void)t;cause_value=value;}
#define zwp_text_input_v3_set_surrounding_text mock_surround
#define zwp_text_input_v3_set_text_change_cause mock_cause
'''
WINDOWS=r'''#define WIN32_LEAN_AND_MEAN
#include "win32.c"
#include <assert.h>
#include <stdio.h>
int main(void){Host h={0};desktop_listen(&h.desktop,1);h.desktop.surrounding.token=123;
 assert(dyn_window_set_surrounding_text(&h,(const uint8_t*)"text",4,0,0,1,0)==-1);
 assert(h.desktop.surrounding.token==123);
 puts("PASS Win32 surrounding correction explicitly unsupported without mutating context");return 0;}
'''
def prefix_fixture():
    path=ROOT/'tests/window-ime-native.py'
    statements=[]
    for node in ast.parse(path.read_text()).body:
        if isinstance(node,ast.With): break
        statements.append(node)
    namespace={'__file__':str(path)}
    exec(compile(ast.Module(body=statements,type_ignores=[]),str(path),'exec'),namespace)
    return namespace
with tempfile.TemporaryDirectory(prefix='dyn-surround-native-') as directory:
    work=Path(directory)
    cc=shlex.split(os.environ.get('CC','cc'))
    if cc and shutil.which(cc[0]):
        (work/'common.c').write_text(COMMON)
        output=work/('common.exe' if os.name=='nt' else 'common')
        subprocess.run([*cc,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(work/'common.c'),'-o',str(output)],check=True)
        subprocess.run([str(output)],check=True,timeout=30)
    else: cc=[]; print('SKIP native surrounding common contracts: C compiler unavailable')
    if sys.platform.startswith('linux') and cc and shutil.which('wayland-scanner') and shutil.which('pkg-config'):
        available=subprocess.run(['pkg-config','--exists','wayland-client','wayland-egl','wayland-cursor','xkbcommon','egl','wayland-protocols']).returncode==0
        if available:
            subprocess.run([sys.executable,str(NATIVE/'build.py'),'--output',str(work/'libdyn_window.so')],check=True,timeout=120)
            old=prefix_fixture()['WAYLAND']; old=old[:old.index('int main(void)')]
            old=old.replace('#include "wayland.c"',EXTRA+'\n#include "wayland.c"')
            (work/'wayland-probe.c').write_text(old+WAYLAND_MAIN)
            flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','wayland-client','wayland-egl','wayland-cursor','xkbcommon','egl'],text=True))
            output=work/'wayland'
            subprocess.run([*cc,'-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-I'+str(NATIVE),'-I'+str(work),str(work/'wayland-probe.c'),str(work/'xdg-shell-protocol.c'),str(work/'text-input-unstable-v3-protocol.c'),*flags,'-o',str(output)],check=True,timeout=120)
            subprocess.run([str(output)],check=True,timeout=30)
    if sys.platform=='darwin' and cc:
        (work/'cocoa-probe.m').write_text(COCOA)
        output=work/'cocoa-probe'
        subprocess.run([*cc,'-fobjc-arc','-Wno-deprecated-declarations','-I'+str(NATIVE),str(work/'cocoa-probe.m'),'-framework','Cocoa','-framework','OpenGL','-o',str(output)],check=True,timeout=120)
        subprocess.run([str(output)],check=True,timeout=30)
    (work/'windows.c').write_text(WINDOWS)
    if sys.platform.startswith('linux') and shutil.which('zig'):
        for target in ('x86_64-windows-gnu','aarch64-windows-gnu'):
            subprocess.run(['zig','cc','-target',target,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(NATIVE),'-c',str(work/'windows.c'),'-o',str(work/(target+'.o'))],check=True,timeout=120)
        if shutil.which('wine'):
            output=work/'windows.exe'
            subprocess.run(['zig','cc','-target','x86_64-windows-gnu','-I'+str(NATIVE),str(work/'windows.c'),'-luser32','-lgdi32','-lopengl32','-limm32','-o',str(output)],check=True,timeout=180)
            subprocess.run(['wine',str(output)],check=True,timeout=60)
    if os.name=='nt' and cc:
        output=work/'windows.exe'
        subprocess.run([*cc,'-std=c11','-Wall','-Wextra','-Werror','-I'+str(NATIVE),str(work/'windows.c'),'-luser32','-lgdi32','-lopengl32','-limm32','-o',str(output)],check=True,timeout=180)
        subprocess.run([str(output)],check=True,timeout=60)
print('PASS native surrounding contracts; Cocoa queries/replacements require native macOS qualification')
