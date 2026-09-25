#!/usr/bin/env python3
"""Build pinned release-test dependencies into a user-owned prefix, never /usr."""
import argparse
import json
import os
from pathlib import Path
import subprocess
ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('packages', nargs='*', help='Default: SDL3, image, ttf, tree-sitter-c, Vulkan headers')
parser.add_argument('--prefix', type=Path, default=ROOT/'build/vendor-deps/install')
args = parser.parse_args()
pins = json.loads((ROOT/'docs/release/toolchain.json').read_text())['sources']
extras = json.loads((ROOT/'compiler/vendor/providers.json').read_text())
packages = args.packages or ['sdl3','sdl3-image','sdl3-ttf','tree-sitter-c','vulkan-headers', *extras]
if set(packages)-(pins.keys()|extras.keys()): parser.error('Unknown dependency')
prefix = args.prefix.resolve(); prefix.mkdir(parents=True,exist_ok=True)
work = ROOT/'build/release-deps'; work.mkdir(parents=True,exist_ok=True)
env = dict(os.environ, CMAKE_PREFIX_PATH=str(prefix)+(os.pathsep+os.environ['CMAKE_PREFIX_PATH'] if os.environ.get('CMAKE_PREFIX_PATH') else ''))
def run(command, **kwargs): subprocess.run(command,env=env,check=True,**kwargs)
for name in packages:
    if name in extras:
        run(['python3',str(ROOT/'compiler/tools/build-vendors.py'),'--prefix',str(prefix),name])
        continue
    pin = pins[name]; source = work/name; build = work/(name+'-build')
    if not source.exists():
        run(['git','init',str(source)])
        run(['git','-C',str(source),'remote','add','origin',pin['repository']])
    run(['git','-C',str(source),'fetch','--depth','1','origin',pin['revision']])
    run(['git','-C',str(source),'checkout','--detach',pin['revision']])
    actual = subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
    assert actual == pin['revision'], (name, actual)
    if name == 'neovim':
        run(['make','-C',str(source),'CMAKE_BUILD_TYPE=Release','CMAKE_INSTALL_PREFIX='+str(prefix),'-j2'])
        run(['make','-C',str(source),'install'])
    elif name == 'tree-sitter-c':
        run(['make','-C',str(source),'-j2'])
        run(['make','-C',str(source),'install','PREFIX='+str(prefix)])
    else:
        options = {'sdl3':['-DSDL_SHARED=ON','-DSDL_STATIC=OFF','-DSDL_TESTS=OFF'],
                   'sdl3-image':['-DSDLIMAGE_VENDORED=OFF','-DSDLIMAGE_SAMPLES=OFF','-DSDLIMAGE_TESTS=OFF'],
                   'sdl3-ttf':['-DSDLTTF_VENDORED=OFF','-DSDLTTF_SAMPLES=OFF'],
                   'vulkan-headers':[]}[name]
        run(['cmake','-S',str(source),'-B',str(build),'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_INSTALL_PREFIX='+str(prefix),'-DCMAKE_INSTALL_LIBDIR=lib','-DBUILD_SHARED_LIBS=ON',*options])
        run(['cmake','--build',str(build),'--parallel','2'])
        run(['cmake','--install',str(build)])
    if name == 'vulkan-headers':
        # Headers-only upstream has no vulkan.pc; use the host loader explicitly.
        pc = prefix/'lib/pkgconfig/vulkan.pc'
        pc.parent.mkdir(parents=True, exist_ok=True)
        pc.write_text(f'prefix={prefix}\nincludedir=${{prefix}}/include\n\nName: Vulkan\nDescription: Pinned Vulkan headers with host Vulkan loader\nVersion: {pin["tag"].removeprefix("v")}\nCflags: -I${{includedir}}\nLibs: -lvulkan\n')
    (work/(name+'.json')).write_text(json.dumps(dict(package=name,source=pin,prefix=str(prefix)),indent=2)+'\n')
print('Installed pinned dependencies into '+str(prefix))
print('Use bin, lib, and lib/pkgconfig from this prefix. Release checks discover its libraries automatically.')
