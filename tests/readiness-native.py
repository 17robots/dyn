#!/usr/bin/env python3
"""Build portable scalar/callback/layout probes; execute only the native host target."""
import argparse, json, os, platform, shlex, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--cross',action='store_true');a=p.parse_args()
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())
work=ROOT/'build/readiness/native';work.mkdir(parents=True,exist_ok=True)
targets=[('x86_64-linux',None,'linux')]
if a.cross: targets += [('aarch64-linux','aarch64-linux-musl','aarch64'),('x86_64-windows','x86_64-windows-gnu','windows'),('aarch64-macos','aarch64-macos-none','macos')]
rows=[]
for target,zig,name in targets:
    provider=work/f'{name}-abi.o'
    cc=['zig','cc','-target',zig] if zig else shlex.split(os.environ.get('CC','cc'))
    subprocess.run([*cc,'-std=c11','-O2','-ffreestanding','-fno-stack-protector','-c',str(ROOT/'tests/release-native/abi.c'),'-o',str(provider)],check=True)
    for release in (False,True):
        output=work/(name+('-release' if release else '-debug')+('.exe' if name=='windows' else ''))
        subprocess.run([DYN,'build',str(ROOT/'tests/release-native'),'--target',target,'--quiet','--no-cache','--link',str(provider),'--output',str(output)]+(['--release'] if release else []),check=True,timeout=120)
        native=target=='x86_64-linux' and platform.machine()=='x86_64'
        if native: subprocess.run([str(output)],check=True,timeout=30)
        rows.append(dict(target=target,release=release,artifact=str(output.relative_to(ROOT)),status='executed' if native else 'cross-linked-only'))
if a.cross:
    for release in (False,True):
        output=work/('aarch64-concurrency'+('-release' if release else '-debug'))
        subprocess.run([DYN,'build',str(ROOT/'tests/release-concurrency'),'--target','aarch64-linux','--quiet','--no-cache','--output',str(output)]+(['--release'] if release else []),check=True,timeout=120)
        rows.append(dict(target='aarch64-linux',release=release,artifact=str(output.relative_to(ROOT)),probe='concurrency',status='cross-linked-only'))
(work/'results.json').write_text(json.dumps(rows,indent=2)+'\n')
print('PASS native ABI/storage/callback/arena probes; cross-linked outputs require native runners')
