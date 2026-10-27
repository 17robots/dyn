#!/usr/bin/env python3
"""Build the native window bridge. Output is an explicit Dyn --link input.
Linux requires wayland-scanner, wayland-protocols, Wayland/EGL headers/libs.
Windows requires a native C toolchain/SDK; macOS requires Xcode command tools.
"""
import argparse, os, pathlib, shlex, subprocess, sys
p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);args=p.parse_args()
root=pathlib.Path(__file__).resolve().parent
out=args.output.resolve();out.parent.mkdir(parents=True,exist_ok=True)
cc=shlex.split(os.environ.get('CC','cc'))
def run(command): subprocess.run(command,check=True)
if sys.platform.startswith('linux'):
    header=out.parent/'xdg-shell-client-protocol.h';source=out.parent/'xdg-shell-protocol.c'
    protocols=subprocess.check_output(['pkg-config','--variable=pkgdatadir','wayland-protocols'],text=True).strip()
    xml=str(pathlib.Path(protocols)/'stable/xdg-shell/xdg-shell.xml')
    run(['wayland-scanner','client-header',xml,str(header)])
    run(['wayland-scanner','private-code',xml,str(source)])
    text_xml=str(pathlib.Path(protocols)/'unstable/text-input/text-input-unstable-v3.xml')
    text_header=out.parent/'text-input-unstable-v3-client-protocol.h';text_source=out.parent/'text-input-unstable-v3-protocol.c'
    run(['wayland-scanner','client-header',text_xml,str(text_header)])
    run(['wayland-scanner','private-code',text_xml,str(text_source)])
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','wayland-client','wayland-egl','wayland-cursor','xkbcommon','egl'],text=True))
    run([*cc,'-shared','-fPIC','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror',f'-I{root}',f'-I{out.parent}',str(root/'wayland.c'),str(source),str(text_source),*flags,'-o',str(out)])
elif sys.platform=='darwin':
    run([*cc,'-dynamiclib','-fobjc-arc','-Wall','-Wextra',str(root/'cocoa.m'),'-framework','Cocoa','-framework','OpenGL','-o',str(out)])
elif sys.platform=='win32':
    run([*cc,'-shared','-std=c11','-Wall','-Wextra',str(root/'win32.c'),'-luser32','-lgdi32','-lopengl32','-limm32',f'-Wl,--out-implib,{out.parent / 'libdyn_window.dll.a'}','-o',str(out)])
else: p.error('unsupported host platform')
print(out)
