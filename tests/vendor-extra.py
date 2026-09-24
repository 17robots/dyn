#!/usr/bin/env python3
"""Exercise optional physics/assets/UI/network/audio providers without hardware."""
import argparse,json,os,shlex,struct,subprocess,tempfile,wave
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--require-all',action='store_true',default=os.environ.get('DYN_REQUIRE_ALL')=='1');a=p.parse_args()
env=dict(os.environ);prefix=ROOT/'build/vendor-deps/install'
for key,suffix in [('PKG_CONFIG_PATH','lib/pkgconfig'),('LD_LIBRARY_PATH','lib'),('DYN_LIBRARY_PATH','lib')]:env[key]=str(prefix/suffix)+(os.pathsep+env[key] if env.get(key) else '')
env['SDL_AUDIODRIVER']='dummy'
env['SDL_VIDEODRIVER']='dummy'
env['SDL_RENDER_DRIVER']='software'
dyn=str(Path(env.get('DYN',ROOT/'build/dyn-release')).resolve())
rows=[]
with tempfile.TemporaryDirectory(prefix='dyn-extra-vendors-') as directory:
 work=Path(directory);wav=work/'tone.wav'
 with wave.open(str(wav),'wb') as out:
  out.setnchannels(1);out.setsampwidth(2);out.setframerate(8000)
  out.writeframes(b''.join(struct.pack('<h',4000 if i%20<10 else -4000) for i in range(800)))
 glb=work/'triangle.glb'
 document={'asset':{'version':'2.0'},'buffers':[{'byteLength':12}],'bufferViews':[{'buffer':0,'byteLength':12}],'accessors':[{'bufferView':0,'componentType':5126,'count':1,'type':'VEC3'}]}
 encoded=json.dumps(document,separators=(',',':')).encode();encoded+=b' '*((-len(encoded))%4)
 binary=struct.pack('<fff',0,1,2)
 chunks=struct.pack('<II',len(encoded),0x4e4f534a)+encoded+struct.pack('<II',len(binary),0x004e4942)+binary
 glb.write_bytes(struct.pack('<III',0x46546c67,2,12+len(chunks))+chunks)
 cases=[('stb','dyn-stb','stb atlas and resize',[]),('microui-sdl3','dyn-microui-sdl3','microui SDL rendering',['--smoke']),('audio-playback','dyn-miniaudio','audio playback completion',[str(wav),'--offline']),('lz4','liblz4','bounded roundtrip',[]),('cgltf','dyn-cgltf','embedded accessor',[str(glb)]),('box2d','dyn-box2d','falling box',[]),('microui','dyn-microui','arena draw commands',[]),('enet','dyn-enet','reliable loopback',[]),('miniaudio','dyn-miniaudio','offline mixing',[str(wav)]),('sdl3-mixer','sdl3-mixer','offline playback',[str(wav)])]
 try:
  for name,package,expected,args in cases:
   if subprocess.run(['pkg-config','--exists',package],env=env).returncode:
    rows.append(dict(package=name,status='skipped'));print('SKIP '+name,flush=True)
    if a.require_all:raise RuntimeError('Missing required provider '+package)
    continue
   version=subprocess.check_output(['pkg-config','--modversion',package],env=env,text=True).strip()
   for release in (False,True):
    binary=work/name
    subprocess.run([dyn,'build',str(ROOT/'projects'/(name+'-example')),'--quiet','--no-cache','--output',str(binary)]+(['--release'] if release else []),env=env,check=True,timeout=120)
    result=subprocess.run([str(binary),*args],env=env,cwd=ROOT,capture_output=True,text=True,timeout=20)
    assert result.returncode==0 and expected in result.stdout,(name,release,result.returncode,result.stdout,result.stderr)
   if name=='stb':
    oracle=work/'stb-oracle'
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','dyn-stb'],env=env,text=True))
    subprocess.run([*shlex.split(env.get('CC','cc')),'-std=c11','-Wall','-Wextra','-Werror',str(ROOT/'tests/vendor-stb-native.c'),*flags,'-o',str(oracle)],env=env,check=True,timeout=60)
    subprocess.run([str(oracle)],env=env,check=True,timeout=20)
   if name=='microui-sdl3':
    oracle=work/'ui-oracle'
    flags=shlex.split(subprocess.check_output(['pkg-config','--cflags','--libs','sdl3','dyn-microui','dyn-microui-sdl3'],env=env,text=True))
    subprocess.run([*shlex.split(env.get('CC','cc')),'-std=c11','-Wall','-Wextra','-Werror',str(ROOT/'tests/vendor-ui-render.c'),*flags,'-o',str(oracle)],env=env,check=True,timeout=60)
    subprocess.run([str(oracle)],env=env,check=True,timeout=20)
   rows.append(dict(package=name,status='passed',version=version,modes=['debug','release']))
   print('PASS '+name+' native debug/release',flush=True)
 except BaseException as error:rows.append(dict(status='failed',error=str(error)));raise
 finally:
  (ROOT/'build').mkdir(exist_ok=True)
  (ROOT/'build/vendor-extra-results.json').write_text(json.dumps(rows,indent=2)+'\n')
