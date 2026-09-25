#!/usr/bin/env python3
"""Incrementally build/install the native grammar artifacts used by just."""
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
PREFIX = Path(os.environ.get('PREFIX', '/usr/local'))
INCLUDE = Path(os.environ.get('INCLUDEDIR', PREFIX/'include'))
LIB = Path(os.environ.get('LIBDIR', PREFIX/'lib'))
PC = Path(os.environ.get('PCLIBDIR', PREFIX/('libdata/pkgconfig' if platform.system() in ('FreeBSD','NetBSD','DragonFly') else 'lib/pkgconfig')))
NAME = 'tree-sitter-dyn'
VERSION = '0.1.0'
DARWIN = platform.system() == 'Darwin'
EXT = 'dylib' if DARWIN else 'so'
cc = shlex.split(os.environ.get('CC', 'cc'))
cflags = shlex.split(os.environ.get('CPPFLAGS', '')) + shlex.split(os.environ.get('CFLAGS', '')) + ['-I'+str(ROOT/'src'), '-std=c11', '-fPIC']

def run(args):
    print(shlex.join(map(str,args)), flush=True)
    subprocess.run(list(map(str,args)), cwd=ROOT, check=True)

def compile(output, inputs, args):
    inputs = [*inputs, Path(__file__), *ROOT.glob('src/tree_sitter/*.h')]
    stamp = BUILD/(output.name+'.build.json')
    identity = json.dumps([list(map(str,args)), [(str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in inputs]])
    if output.exists() and stamp.exists() and stamp.read_text() == identity:
        return
    stamp.unlink(missing_ok=True)
    run(args)
    stamp.write_text(identity)

def generate(force=False):
    parser = ROOT/'src/parser.c'
    if force or not parser.exists() or any(p.stat().st_mtime_ns > parser.stat().st_mtime_ns for p in (ROOT/'grammar.js', ROOT/'tree-sitter.json')):
        ts = os.environ.get('TS', 'tree-sitter')
        run([sys.executable, ROOT/'tools/check-generator.py', ts])
        run([ts, 'generate'])

def main(action):
    if platform.system() == 'Windows':
        sys.exit('Native Windows grammar builds are not supported')
    if action == 'clean':
        if BUILD == Path('/') or ROOT.is_relative_to(BUILD):
            sys.exit('Refusing unsafe BUILD for clean')
        if BUILD.exists(): shutil.rmtree(BUILD)
        for p in [*ROOT.glob('src/*.o'), ROOT/(NAME+'.pc'), ROOT/('lib'+NAME+'.a'), ROOT/('lib'+NAME+'.'+EXT)]:
            p.unlink(missing_ok=True)
        return
    if action == 'generate':
        generate(True)
        return
    generate()
    BUILD.mkdir(parents=True, exist_ok=True)
    major = re.search(r'#define LANGUAGE_VERSION (\d+)', (ROOT/'src/parser.c').read_text())[1]
    soname = f'{major}.0.dylib' if DARWIN else f'so.{major}.0'
    soname_major = f'{major}.dylib' if DARWIN else f'so.{major}'
    def dest(p): return Path(os.environ.get('DESTDIR','') + str(p))
    if action == 'uninstall':
        for p in [LIB/('lib'+NAME+'.'+s) for s in ('a', EXT, soname, soname_major)] + [INCLUDE/'tree_sitter'/(NAME+'.h'), PC/(NAME+'.pc')]:
            dest(p).unlink(missing_ok=True)
        return
    objects=[]
    for source in sorted(ROOT.glob('src/*.c')):
        obj = source.with_suffix('.o')
        compile(obj, [source], [*cc,*cflags,'-c',source,'-o',obj])
        objects.append(obj)
    if action == 'highlights':
        output=BUILD/'highlights-test'
        compile(output, [ROOT/'test/native/highlights.c',*objects], [*cc,*cflags,ROOT/'test/native/highlights.c',*objects,'-ltree-sitter','-o',output])
        return
    archive=ROOT/('lib'+NAME+'.a')
    compile(archive, objects, [*shlex.split(os.environ.get('AR','ar')),*shlex.split(os.environ.get('ARFLAGS','rcs')),archive,*objects])
    shared=ROOT/('lib'+NAME+'.'+EXT)
    link = ['-dynamiclib', f'-Wl,-install_name,{LIB}/lib{NAME}.{soname},-rpath,@executable_path/../Frameworks'] if DARWIN else ['-shared',f'-Wl,-soname,lib{NAME}.{soname}']
    compile(shared, objects, [*cc,*shlex.split(os.environ.get('LDFLAGS','')),*link,*objects,*shlex.split(os.environ.get('LDLIBS','')),'-o',shared])
    if os.environ.get('STRIP'): run([*shlex.split(os.environ['STRIP']), shared])
    pc=(ROOT/'bindings/c'/f'{NAME}.pc.in').read_text()
    for key,value in {'PROJECT_VERSION':VERSION,'CMAKE_INSTALL_LIBDIR':os.path.relpath(LIB,PREFIX) if LIB.is_relative_to(PREFIX) else LIB,'CMAKE_INSTALL_INCLUDEDIR':os.path.relpath(INCLUDE,PREFIX) if INCLUDE.is_relative_to(PREFIX) else INCLUDE,'PROJECT_DESCRIPTION':'Dyn grammar for Tree-sitter','PROJECT_HOMEPAGE_URL':'https://github.com/17robots/dyn','CMAKE_INSTALL_PREFIX':PREFIX}.items():
        pc=pc.replace('@'+key+'@',str(value))
    pcpath=ROOT/(NAME+'.pc')
    if not pcpath.exists() or pcpath.read_text()!=pc: pcpath.write_text(pc)
    if action == 'install':
        for source,target in [(ROOT/'bindings/c'/(NAME+'.h'),INCLUDE/'tree_sitter'/(NAME+'.h')),(pcpath,PC/pcpath.name),(archive,LIB/archive.name),(shared,LIB/('lib'+NAME+'.'+soname))]:
            target=dest(target); target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target); target.chmod(0o755 if source==shared else 0o644)
        for name,target in [(soname_major,soname),(EXT,soname_major)]:
            path=dest(LIB/('lib'+NAME+'.'+name)); path.unlink(missing_ok=True); path.symlink_to('lib'+NAME+'.'+target)

if __name__ == '__main__':
    try: main(sys.argv[1])
    except (OSError,subprocess.CalledProcessError) as error: sys.exit(str(error))
