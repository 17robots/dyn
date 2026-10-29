#!/usr/bin/env python3
"""Build compute UI bridge; requires Vulkan headers/loader and glslangValidator."""
import argparse,os,pathlib,shlex,struct,subprocess,sys
p=argparse.ArgumentParser();p.add_argument('--output',type=pathlib.Path,required=True);p.add_argument('--include',action='append',default=[]);a=p.parse_args()
root=pathlib.Path(__file__).resolve().parent;out=a.output.resolve();out.parent.mkdir(parents=True,exist_ok=True)
shader=out.parent/'ui.comp.spv'
subprocess.run(['glslangValidator','-V',str(root/'ui.comp'),'-o',str(shader)],check=True)
raw=shader.read_bytes();words=struct.unpack('<'+'I'*(len(raw)//4),raw)
(out.parent/'shader.h').write_text('#include <stdint.h>\nstatic const uint32_t dyn_ui_shader[]={'+','.join(hex(x) for x in words)+'};\n')
libraries=['-lvulkan-1',f'-Wl,--out-implib,{out.parent / 'libdyn_ui_vulkan.dll.a'}'] if sys.platform=='win32' else ['-lvulkan']
mode=['-dynamiclib'] if sys.platform=='darwin' else ['-shared','-fPIC']
command=[*shlex.split(os.environ.get('CC','cc')),*mode,'-std=c11','-Wall','-Wextra','-Werror',f'-I{out.parent}',*[f'-I{x}' for x in a.include],str(root/'renderer.c'),*libraries,'-o',str(out)]
subprocess.run(command,check=True)
print(out)
