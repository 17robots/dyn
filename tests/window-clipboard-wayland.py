#!/usr/bin/env python3
"""Production Wayland clipboard callbacks with real nonblocking transfer pipes."""
import ast
import os
from pathlib import Path
import shlex
import shutil
import sys
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
NATIVE=ROOT/'vendor/window/native'
EXTRA=r'''
#include <unistd.h>
static int receive_writer=-1, destroys;
static struct wl_data_source *mock_create(struct wl_data_device_manager *m){(void)m;static uintptr_t id=100;return (struct wl_data_source*)++id;}
static int mock_listener(struct wl_data_source*s,const struct wl_data_source_listener*l,void*p){(void)s;(void)l;(void)p;return 0;}
static void mock_offer(struct wl_data_source*s,const char*m){(void)s;(void)m;}
static void mock_selection(struct wl_data_device*d,struct wl_data_source*s,uint32_t n){(void)d;(void)s;(void)n;}
static void mock_destroy(struct wl_data_source*s){(void)s;destroys++;}
static void mock_receive(struct wl_data_offer*o,const char*m,int fd){(void)o;assert(!strcmp(m,"text/plain;charset=utf-8"));receive_writer=dup(fd);assert(receive_writer>=0);}
#define wl_data_device_manager_create_data_source mock_create
#define wl_data_source_add_listener mock_listener
#define wl_data_source_offer mock_offer
#define wl_data_device_set_selection mock_selection
#define wl_data_source_destroy mock_destroy
#define wl_data_offer_receive mock_receive
'''
MAIN=r'''
static void remote(Host*h,const uint8_t*data,uint32_t length) {
 dyn_window_request_paste_snapshot(h);assert(dyn_window_paste_pending(h)&&dyn_window_paste_status(h)==-4);
 int flags=fcntl(receive_writer,F_GETFL);assert(fcntl(receive_writer,F_SETFL,flags|O_NONBLOCK)==0);
 uint32_t at=0;
 while(at<length){ssize_t n=write(receive_writer,data+at,length-at);if(n>0)at+=(uint32_t)n;else assert(errno==EAGAIN);receive_clipboard(h);}
 close(receive_writer);receive_writer=-1;receive_clipboard(h);assert(!dyn_window_paste_pending(h));
}
int main(void) {
 Host h={0};h.receive_fd=-1;h.clipboard_status=-4;h.serial=7;
 h.data_manager=(struct wl_data_device_manager*)1;h.data_device=(struct wl_data_device*)1;
 desktop_listen(&h.desktop,1);
 const uint32_t length=1200000;uint8_t *large=malloc(length);assert(large);memset(large,'a',length);
 assert(dyn_window_try_set_clipboard(&h,large,length)==1);
 assert(h.clipboard_owned_length==length);
 const uint8_t bad[]={0xc0,0x80}, nul[]={'a',0};
 struct wl_data_source *old=h.source;
 assert(dyn_window_try_set_clipboard(&h,bad,2)==-3&&h.source==old);
 assert(dyn_window_try_set_clipboard(&h,nul,2)==-3&&h.source==old);
 assert(dyn_window_try_set_clipboard(&h,large,WAYLAND_CLIPBOARD_LIMIT+1)==-2&&h.source==old);
 dyn_window_request_paste_snapshot(&h);const uint8_t *snapshot;
 assert(dyn_window_paste_status(&h)==1&&dyn_window_clipboard_get(&h,&snapshot)==length&&!memcmp(snapshot,large,length));
 assert(!h.desktop.event_count&&!h.desktop.event_dropped);
 dyn_window_request_paste(&h);assert(!h.desktop.event_count&&h.desktop.event_dropped==1);
 dyn_window_event event;assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW);
 int pipefd[2];assert(pipe2(pipefd,O_NONBLOCK|O_CLOEXEC)==0);
 source_send(&h,h.source,"text/plain;charset=utf-8",pipefd[1]);assert(h.clipboard_sends);
 assert(dyn_window_try_set_clipboard(&h,(const uint8_t*)"changed",7)==1);
 uint32_t got=0;uint8_t buffer[16384];
 while(h.clipboard_sends){ssize_t n=read(pipefd[0],buffer,sizeof(buffer));if(n>0){for(ssize_t i=0;i<n;i++)assert(buffer[i]=='a');got+=(uint32_t)n;}send_clipboards(&h);}
 for(;;){ssize_t n=read(pipefd[0],buffer,sizeof(buffer));if(n<=0)break;for(ssize_t i=0;i<n;i++)assert(buffer[i]=='a');got+=(uint32_t)n;}
 assert(got==length);close(pipefd[0]);
 assert(pipe2(pipefd,O_NONBLOCK|O_CLOEXEC)==0);close(pipefd[0]);
 source_send(&h,h.source,"text/plain;charset=utf-8",pipefd[1]);assert(!h.clipboard_sends);
 source_cancelled(&h,h.source);h.offer=(struct wl_data_offer*)1;h.offer_text=1;
 remote(&h,large,length);assert(dyn_window_paste_status(&h)==1&&dyn_window_clipboard_get(&h,&snapshot)==length&&!memcmp(snapshot,large,length));
 assert(!h.desktop.event_count&&!h.desktop.event_dropped);
 remote(&h,bad,2);assert(dyn_window_paste_status(&h)==-3&&dyn_window_clipboard_get(&h,&snapshot)==length);
 const uint8_t truncated[]={0xe2,0x82};remote(&h,truncated,2);assert(dyn_window_paste_status(&h)==-3&&h.clipboard_received_length==length);
 remote(&h,nul,2);assert(dyn_window_paste_status(&h)==-3);
 dyn_window_request_paste_snapshot(&h);int original=h.receive_fd;dyn_window_request_paste_snapshot(&h);assert(h.receive_fd==original&&h.clipboard_status==-4);
 dyn_window_request_paste(&h);assert(h.desktop.event_dropped==1);close(receive_writer);receive_clipboard(&h);assert(h.clipboard_status==1&&h.clipboard_received_length==0);
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_OVERFLOW);
 remote(&h,large,length);assert(h.clipboard_received_length==length);
 uint8_t *oversize=malloc(WAYLAND_CLIPBOARD_LIMIT+1);assert(oversize);memset(oversize,'x',WAYLAND_CLIPBOARD_LIMIT+1);remote(&h,oversize,WAYLAND_CLIPBOARD_LIMIT+1);free(oversize);assert(h.clipboard_status==-2&&h.clipboard_received_length==length);
 dyn_window_request_paste_snapshot(&h);h.clipboard_deadline=now_ms()-1;receive_clipboard(&h);assert(!dyn_window_paste_pending(&h)&&h.clipboard_status==0&&h.clipboard_received_length==length);close(receive_writer);
 h.offer=NULL;dyn_window_request_paste_snapshot(&h);assert(h.clipboard_status==1&&!h.clipboard_received_length);
 assert(dyn_window_try_set_clipboard(&h,NULL,0)==1);dyn_window_request_paste(&h);
 assert(desktop_next(&h.desktop,&event)&&event.kind==DYN_EVENT_CLIPBOARD&&!event.text_length&&event.button);
 uint8_t small[600];memset(small,'z',sizeof(small));memcpy(small+255,"\xf0\x9f\x98\x80",4);
 assert(dyn_window_try_set_clipboard(&h,small,sizeof(small))==1);dyn_window_request_paste(&h);
 unsigned offset=0,chunks=0;while(desktop_next(&h.desktop,&event)){assert(event.kind==DYN_EVENT_CLIPBOARD&&event.x==(int)offset&&event.width==600);assert(!memcmp(event.text,small+offset,event.text_length));offset+=event.text_length;chunks++;assert(event.button==(offset==600));}assert(offset==600&&chunks==3);
 free(h.clipboard_owned);free(h.clipboard_received);free(h.clipboard_incoming);free(large);
 puts("PASS Wayland checked clipboard: 1.2MB owned/send/receive, immutable in-flight sends, empty, UTF8/NUL/capacity rejection, atomic events, busy retry and peer close");
}
'''
def prefix_fixture():
    path=ROOT/'tests/window-ime-native.py';statements=[]
    for node in ast.parse(path.read_text()).body:
        if isinstance(node,ast.With):break
        statements.append(node)
    ns={'__file__':str(path)}
    exec(compile(ast.Module(body=statements,type_ignores=[]),str(path),'exec'),ns)
    return ns['WAYLAND'].split('int main(void)')[0].split('static void drain(')[0]
if not sys.platform.startswith('linux') or not shutil.which('wayland-scanner') or not shutil.which('pkg-config') or subprocess.run(['pkg-config','--exists','wayland-client','wayland-egl','wayland-cursor','xkbcommon','egl','wayland-protocols']).returncode:
    print('SKIP Wayland clipboard: native Wayland build dependencies unavailable')
    sys.exit(0)
with tempfile.TemporaryDirectory(prefix='dyn-clipboard-wayland-') as directory:
    work=Path(directory)
    subprocess.run(['python3',str(NATIVE/'build.py'),'--output',str(work/'libdyn_window.so')],check=True,timeout=120)
    source=prefix_fixture().replace('#include "wayland.c"',EXTRA+'\n#include "wayland.c"')+MAIN
    (work/'probe.c').write_text(source)
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','wayland-client','wayland-egl','wayland-cursor','xkbcommon','egl'],text=True))
    subprocess.run([*shlex.split(os.environ.get('CC','cc')),'-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror','-I'+str(NATIVE),'-I'+str(work),str(work/'probe.c'),str(work/'xdg-shell-protocol.c'),str(work/'text-input-unstable-v3-protocol.c'),*flags,'-o',str(work/'probe')],check=True,timeout=120)
    subprocess.run([str(work/'probe')],check=True,timeout=30)
