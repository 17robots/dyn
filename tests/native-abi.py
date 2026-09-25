#!/usr/bin/env python3
"""Compare shipped binding layouts with installed headers; exercise a C callback."""
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn')).resolve())
CC=shlex.split(os.environ.get('CC','cc'))
def pkg(*args): return subprocess.check_output(['pkg-config',*args],text=True).strip()
if subprocess.run(['pkg-config','--exists','sdl3','vulkan']).returncode:
    print('SKIP native ABI: SDL3/Vulkan development headers unavailable')
    raise SystemExit(1 if os.environ.get('DYN_REQUIRE_ALL') == '1' else 0)
layouts=[
 ('Event','SDL_Event',[]),
 ('AudioSpec','SDL_AudioSpec',[('format','format'),('channels','channels'),('frequency','freq')]),
 ('FColor','SDL_FColor',[(a,b) for a,b in zip(['red','green','blue','alpha'],['r','g','b','a'])]),
 ('GpuColorTargetInfo','SDL_GPUColorTargetInfo',[(x,x) for x in 'texture mip_level layer_or_depth_plane clear_color load_op store_op resolve_texture resolve_mip_level resolve_layer cycle cycle_resolve_texture padding1 padding2'.split()]),
 ('GpuShaderInfo','SDL_GPUShaderCreateInfo',[(x,x) for x in 'code_size code entrypoint format stage'.split()]+[('samplers','num_samplers'),('buffer_textures','num_storage_textures'),('buffer_buffers','num_storage_buffers'),('uniform_buffers','num_uniform_buffers'),('properties','props')]),
 ('GpuTextureInfo','SDL_GPUTextureCreateInfo',[('kind','type'),('format','format'),('usage','usage'),('width','width'),('height','height'),('layers_or_depth','layer_count_or_depth'),('levels','num_levels'),('samples','sample_count'),('properties','props')]),
 ('GpuBufferInfo','SDL_GPUBufferCreateInfo',[('usage','usage'),('size','size'),('properties','props')]),
]
c='#include <SDL3/SDL.h>\n#if __has_include(<vulkan/vulkan.h>)\n#include <vulkan/vulkan.h>\n#define VK_SIZE sizeof(VkInstance)\n#define VK_PROC_SIZE sizeof(PFN_vkVoidFunction)\n#else\n#define VK_SIZE 0\n#define VK_PROC_SIZE 0\n#endif\n#include <linux/stat.h>\n#include <stddef.h>\n#include <stdio.h>\n'
c+='void probe_callback(SDL_AudioStreamCallback cb, void *data) { cb(data, NULL, 17, 29); }\n'
c+='int main(void) {\n'
for _,ct,fields in layouts:
    c+=f'printf("%zu %zu",sizeof({ct}),_Alignof({ct}));\n'
    for _,cf in fields: c+=f'printf(" %zu",offsetof({ct},{cf}));\n'
    c+='puts("");\n'
c+='printf("%zu %zu %zu %zu %zu %zu\\n", (size_t)VK_SIZE,(size_t)VK_PROC_SIZE,offsetof(struct statx,stx_mode),offsetof(struct statx,stx_ino),offsetof(struct statx,stx_size),offsetof(struct statx,stx_dev_major)); return 0; }\n'
with tempfile.TemporaryDirectory(prefix='dyn-native-abi-') as directory:
    p=Path(directory);(p/'probe.c').write_text(c)
    flags=shlex.split(pkg('--cflags','sdl3','vulkan'))
    subprocess.run([*CC,*flags,str(p/'probe.c'),'-o',str(p/'probe')],check=True)
    rows=subprocess.check_output([str(p/'probe')],text=True).splitlines()
    # Remove C entry point before linking the callback provider into Dyn.
    (p/'callback.c').write_text(c[:c.index('int main(void)')])
    subprocess.run([*CC,*flags,'-fno-stack-protector','-c',str(p/'callback.c'),'-o',str(p/'callback.o')],check=True)
    source='''use "vendor/sdl3" sdl
use "vendor/vulkan" vk
extern fn probe_callback(callback: sdl.AudioCallback, data: rawptr)
fn callback(data: rawptr, stream: sdl.AudioStream, additional: i32, total: i32) {
  value := #cast(*i32) data
  if stream != nil || additional != 17 || total != 29 { #panic("callback ABI") }
  value.* = additional + total
}
fn main() {
'''
    for (dt,_,fields),row in zip(layouts,rows):
        size,align,*offsets=map(int,row.split());name=dt.lower()
        source+=f'if #sizeof(sdl.{dt}) != {size} || #alignof(sdl.{dt}) != {align} {{ #panic("{dt} layout") }}\n'
        if fields: source+=f'{name} := sdl.{dt}{{}}\n'
        for (df,_),offset in zip(fields,offsets):
            source+=f'if (#cast(usize) &{name}.{df}) - (#cast(usize) &{name}) != {offset} {{ #panic("{dt}.{df} offset") }}\n'
    instance,proc,mode,ino,size,dev=map(int,rows[-1].split())
    assert (mode,ino,size,dev)==(28,32,40,136),'Linux statx layout changed'
    if instance: source+=f'if #sizeof(vk.Instance) != {instance} || #sizeof(vk.Procedure) != {proc} {{ #panic("Vulkan handles") }}\n'
    if not instance:
        if os.environ.get('DYN_REQUIRE_ALL') == '1': raise SystemExit('Vulkan development headers required')
        print('SKIP Vulkan ABI: loader present, development headers absent')
    source+='value: i32 = 0\nprobe_callback(&callback, #cast(rawptr) &value)\nif value != 46 { #panic("callback return") }\n}\n'
    (p/'main.dyn').write_text(source)
    for mode in ([],['--release']):
        subprocess.run([DYN,'build',str(p),'--quiet','--no-cache','--link',str(p/'callback.o'),'--output',str(p/'run'),*mode],cwd=ROOT,check=True)
        subprocess.run([str(p/'run')],check=True)
print('PASS native ABI layouts/offsets/callback, SDL',pkg('--modversion','sdl3'),'Vulkan',pkg('--modversion','vulkan'))
