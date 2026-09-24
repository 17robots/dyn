#!/usr/bin/env python3
"""Build the pinned optional providers and small Dyn ABI adapters on Linux."""
import argparse,json,os,platform,shlex,shutil,subprocess
from pathlib import Path
LOCATION=Path(__file__).resolve().parents[1]
VENDOR=LOCATION/'vendor' if (LOCATION/'vendor/providers.json').is_file() else LOCATION/'share/dyn/vendor'
DEFAULT_BUILD=LOCATION.parent/'build' if VENDOR==LOCATION/'vendor' else Path.cwd()/'build'
pins=json.loads((VENDOR/'providers.json').read_text())
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('packages',nargs='*')
p.add_argument('--prefix',type=Path,default=DEFAULT_BUILD/'vendor-deps/install')
p.add_argument('--sources',type=Path,default=DEFAULT_BUILD/'extra-vendor-sources')
a=p.parse_args();packages=a.packages or list(pins)
if set(packages)-pins.keys():p.error('Unknown optional provider')
packages=list(dict.fromkeys(packages))
if 'microui-sdl3' in packages:
 if 'microui' in packages:packages.remove('microui')
 packages.insert(0,'microui')
if platform.system()!='Linux':p.error('Native adapter build currently qualified on Linux only')
prefix=a.prefix.resolve();sources=a.sources.resolve();prefix.mkdir(parents=True,exist_ok=True);sources.mkdir(parents=True,exist_ok=True)
(prefix/'lib/pkgconfig').mkdir(parents=True,exist_ok=True)
env=dict(os.environ)
for key,suffix in [('PKG_CONFIG_PATH','lib/pkgconfig'),('LD_LIBRARY_PATH','lib'),('CMAKE_PREFIX_PATH','')]:
 env[key]=str(prefix/suffix)+(os.pathsep+env[key] if env.get(key) else '')
cc=shlex.split(env.get('CC','cc'))
def run(cmd,**kw):subprocess.run(cmd,env=env,check=True,**kw)
def shared(name,inputs,includes=(),links=()):
 run([*cc,'-std=c11','-O2','-fPIC','-shared',*[str(s) for s in inputs],*['-I'+str(s) for s in includes],'-L'+str(prefix/'lib'),'-Wl,-rpath,$ORIGIN',*map(str,links),'-o',str(prefix/'lib'/('lib'+name+'.so'))])
def pc(package,library,version):
 (prefix/'lib/pkgconfig'/(package+'.pc')).write_text(f'prefix={prefix}\nlibdir=${{prefix}}/lib\nincludedir=${{prefix}}/include\n\nName: {package}\nDescription: pinned optional provider for Dyn\nVersion: {version}\nLibs: -L${{libdir}} -l{library}\nCflags: -I${{includedir}}\n')
for name in packages:
 pin=pins[name];source=sources/name;build=sources/(name+'-build')
 if not source.exists():
  run(['git','init',str(source)]);run(['git','-C',str(source),'remote','add','origin',pin['repository']])
 current=subprocess.run(['git','-C',str(source),'rev-parse','HEAD'],capture_output=True,text=True).stdout.strip()
 if current!=pin['revision']:
  run(['git','-C',str(source),'fetch','--depth','1','origin',pin['revision']]);run(['git','-C',str(source),'checkout','--detach',pin['revision']])
 if name in ('box2d','enet','sdl3-mixer'):
  options={'box2d':['-DBOX2D_SAMPLES=OFF','-DBOX2D_UNIT_TESTS=OFF','-DBOX2D_BENCHMARKS=OFF'],
   'enet':['-DCMAKE_POLICY_VERSION_MINIMUM=3.5'],
   'sdl3-mixer':['-DSDLMIXER_VENDORED=OFF','-DSDLMIXER_EXAMPLES=OFF','-DSDLMIXER_TESTS=OFF',*[f'-DSDLMIXER_{codec}=OFF' for codec in ('FLAC','GME','MOD','MP3','MIDI','OPUS','VORBIS_STB','VORBIS_VORBISFILE','VORBIS_TREMOR','WAVPACK')]]}[name]
  run(['cmake','-S',str(source),'-B',str(build),'-DCMAKE_BUILD_TYPE=Release','-DCMAKE_INSTALL_PREFIX='+str(prefix),'-DCMAKE_INSTALL_LIBDIR=lib','-DCMAKE_POSITION_INDEPENDENT_CODE=ON','-DBUILD_SHARED_LIBS=ON',*options])
  run(['cmake','--build',str(build),'--parallel','2']);run(['cmake','--install',str(build)])
 if name=='box2d':shared('dyn_box2d',[VENDOR/'box2d/bridge.c'],[source/'include'],['-lbox2d','-lm']);pc('dyn-box2d','dyn_box2d',pin['version'])
 elif name=='enet':
  archive=next(build.rglob('libenet.a'))
  shared('dyn_enet',[VENDOR/'enet/bridge.c'],[source/'include'],['-Wl,--whole-archive',archive,'-Wl,--no-whole-archive']);pc('dyn-enet','dyn_enet',pin['version'])
 elif name=='cgltf':shared('dyn_cgltf',[VENDOR/'cgltf/bridge.c'],[source],['-lm']);pc('dyn-cgltf','dyn_cgltf',pin['version'])
 elif name=='microui':
  # The pinned upstream byte buffer and variable command sizes are unaligned.
  # Stage the minimal C11 fix; preserve the pristine upstream checkout.
  build.mkdir(parents=True,exist_ok=True)
  header=(source/'src/microui.h').read_text()
  before='mu_stack(char, MU_COMMANDLIST_SIZE) command_list;'
  if header.count(before)!=1:raise RuntimeError('microui header patch no longer applies')
  header=header.replace(before,'struct { int idx; _Alignas(mu_Command) char items[MU_COMMANDLIST_SIZE]; } command_list;')
  implementation=(source/'src/microui.c').read_text()
  before='mu_Command* mu_push_command(mu_Context *ctx, int type, int size) {'
  if implementation.count(before)!=1:raise RuntimeError('microui command patch no longer applies')
  implementation=implementation.replace(before,before+'\n  size = (size + (int)_Alignof(mu_Command) - 1) & ~((int)_Alignof(mu_Command) - 1);')
  (build/'microui.h').write_text(header);(build/'microui.c').write_text(implementation)
  shared('dyn_microui',[VENDOR/'microui/bridge.c',build/'microui.c'],[build]);pc('dyn-microui','dyn_microui',pin['version'])
 elif name=='microui-sdl3':
  flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl3'],env=env,text=True))
  shared('dyn_microui_sdl3',[VENDOR/'sdl3/microui/bridge.c'],links=['-ldyn_microui',*flags]);pc('dyn-microui-sdl3','dyn_microui_sdl3',pin['version'])
 elif name=='miniaudio':shared('dyn_miniaudio',[VENDOR/'miniaudio/bridge.c'],[source],['-lm','-lpthread','-ldl']);pc('dyn-miniaudio','dyn_miniaudio',pin['version'])
 elif name=='stb':
  # Keep SIMD, but replace scalar type-punned/unaligned byte-buffer accesses.
  build.mkdir(parents=True,exist_ok=True)
  header=(source/'stb_image_resize2.h').read_text()
  fixes=[('*(int*)(output-4) = stbir__simdi_to_int( i0 );','{ int value=stbir__simdi_to_int(i0); memcpy(output-4,&value,sizeof(value)); }',2),
         ('*(int*)( sd + ofs_to_dest ) = *(int*) sd;','memmove(sd + ofs_to_dest,sd,sizeof(int));',2),
         ('*(stbir_uint64*)( sd + ofs_to_dest ) = *(stbir_uint64*) sd;','memmove(sd + ofs_to_dest,sd,sizeof(stbir_uint64));',1)]
  for before,after,count in fixes:
   if header.count(before)!=count:raise RuntimeError('stb alignment patch no longer applies')
   header=header.replace(before,after)
  (build/'stb_image_resize2.h').write_text(header)
  shared('dyn_stb',[VENDOR/'stb/bridge.c'],[build,source],['-lm']);pc('dyn-stb','dyn_stb',pin['version'])
  shared('dyn_stb_resize',[VENDOR/'stb/raw_resize.c'],[build,source],['-lm'])
 elif name=='lz4':
  shared('lz4',[source/'lib'/f for f in ('lz4.c','lz4hc.c','lz4frame.c','xxhash.c')],[source/'lib']);pc('liblz4','lz4',pin['version'])
 # Keep licenses alongside installed adapters, including upstream codec notices.
 notice=prefix/'share/dyn-vendor-licenses'/name;notice.mkdir(parents=True,exist_ok=True)
 for candidate in source.rglob('*'):
  if candidate.is_file() and not any(part in ('.git','build') for part in candidate.relative_to(source).parts) and ('LICENSE' in candidate.name.upper() or candidate.name.upper().startswith('COPYING')):
   target=notice/candidate.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(candidate,target)
 if name in ('microui','stb'):(notice/'DYN-CHANGES.txt').write_text('Dyn builds apply C alignment fixes in staged sources; see dyn-build-vendors. Upstream checkout remains unchanged.\n')
 (notice/'source.json').write_text(json.dumps(pin,indent=2)+'\n')
 print('BUILT '+name,flush=True)
print('Native providers installed: '+str(prefix))
