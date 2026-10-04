#!/usr/bin/env python3
"""Build pinned optional test providers into BUILD; never install into the host."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
PREFIX = BUILD/'vendor-deps/install'
SOURCES = BUILD/'extra-vendor-sources'
PINS = json.loads((ROOT/'vendor/qualification-sources.json').read_text())
env = dict(os.environ)
for key, suffix in [('PKG_CONFIG_PATH','lib/pkgconfig'),('LD_LIBRARY_PATH','lib'),('CMAKE_PREFIX_PATH','')]:
    env[key] = str(PREFIX/suffix)+(os.pathsep+env[key] if env.get(key) else '')
def run(command, **kwargs):
    subprocess.run(list(map(str,command)),env=env,check=True,timeout=1200,**kwargs)
for name,pin in PINS.items():
    source = SOURCES/name
    output = SOURCES/(name+'-build')
    if not source.exists():
        source.mkdir(parents=True)
        run(['git','init',source])
        run(['git','-C',source,'remote','add','origin',pin['repository']])
    current = subprocess.run(['git','-C',str(source),'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
    if current != pin['revision']:
        run(['git','-C',source,'fetch','--depth','1','origin',pin['revision']])
        run(['git','-C',source,'checkout','--detach',pin['revision']])
    dirty = subprocess.check_output(['git','-C',str(source),'status','--porcelain','--untracked-files=no'],text=True)
    if dirty: raise RuntimeError('Modified provider source cannot be qualified as a pristine pin: '+str(source))
    if name == 'tree-sitter-c':
        (PREFIX/'lib/pkgconfig').mkdir(parents=True,exist_ok=True)
        flags = shlex.split(subprocess.check_output(['pkg-config','--cflags','tree-sitter'],env=env,text=True))
        run([*shlex.split(env.get('CC','cc')),'-O2','-fPIC','-shared','-I'+str(source/'src'),*flags,source/'src/parser.c','-o',PREFIX/'lib/libtree-sitter-c.so'])
        (PREFIX/'lib/pkgconfig/tree-sitter-c.pc').write_text(f'prefix={PREFIX}\nlibdir=${{prefix}}/lib\n\nName: tree-sitter-c\nDescription: pinned C grammar for native tests\nVersion: 0.24.1\nLibs: -L${{libdir}} -ltree-sitter-c\n')
        continue
    options = {
        'sdl3':['-DSDL_SHARED=ON','-DSDL_STATIC=OFF','-DSDL_TESTS=OFF','-DSDL_TEST_LIBRARY=OFF'],
        'sdl3-image':['-DSDLIMAGE_VENDORED=OFF','-DSDLIMAGE_SAMPLES=OFF','-DSDLIMAGE_TESTS=OFF'],
        'sdl3-ttf':['-DSDLTTF_VENDORED=OFF','-DSDLTTF_SAMPLES=OFF'],
        'vulkan-headers':['-DVULKAN_HEADERS_ENABLE_TESTS=OFF'],
    }[name]
    run(['cmake','-S',source,'-B',output,'-DCMAKE_BUILD_TYPE=Release','-DBUILD_SHARED_LIBS=ON','-DCMAKE_INSTALL_PREFIX='+str(PREFIX),'-DCMAKE_INSTALL_LIBDIR=lib',*options])
    run(['cmake','--build',output,'--parallel',env.get('VENDOR_JOBS','2')])
    run(['cmake','--install',output])
run([sys.executable,ROOT/'tools/build-vendors.py','--prefix',PREFIX,'--sources',SOURCES])
(PREFIX/'qualification-sources.json').write_text(json.dumps(PINS,indent=2)+'\n')
print('PASS pinned optional test providers built in '+str(PREFIX))
