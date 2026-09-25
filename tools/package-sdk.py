#!/usr/bin/env python3
"""Package and smoke-test only this compiler and its runtime/SDK."""
import importlib.util
import gzip,hashlib,json,os,platform,re,shutil,subprocess,sys,tarfile,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BUILD=Path(os.environ.get('BUILD',ROOT/'build')).resolve()
DIST=BUILD/'dist';DIST.mkdir(parents=True,exist_ok=True)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
with tempfile.TemporaryDirectory(prefix='dyn-sdk-') as temporary:
    work=Path(temporary);sdk=work/'stage/dyn-sdk'
    subprocess.run(['python3',str(ROOT/'tools/install.py')],env=dict(os.environ,BUILD=str(BUILD),DESTDIR=str(work/'stage'),PREFIX='/dyn-sdk'),check=True)
    for name in ('README.md','LICENSE','THIRD_PARTY_NOTICES.md','grammar.lock.json'):
        shutil.copy2(ROOT/name,sdk/name)
    spec=importlib.util.spec_from_file_location('bundle_linux',ROOT/'tools/bundle-linux.py')
    bundler=importlib.util.module_from_spec(spec);spec.loader.exec_module(bundler)
    distribution=bundler.bundle(sdk)
    version=subprocess.check_output([str(sdk/'bin/dyn'),'version'],text=True).strip()
    if not re.fullmatch(r'dyn [0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z.-]+)?',version):raise RuntimeError('Invalid compiler version')
    runtime_sources=bundler.runtime_sources(DIST,version.removeprefix('dyn '))
    dependencies=subprocess.check_output(['ldd',str(sdk/'bin/dyn')],text=True)
    if 'not found' in dependencies:raise RuntimeError(dependencies)
    manifest=dict(runtime_sources=runtime_sources,distribution=distribution,version=version,host=platform.platform(),scope='Standalone compiler and runtime/SDK',dependencies=dependencies.splitlines(),files={str(p.relative_to(sdk)):sha(p) for p in sorted(sdk.rglob('*')) if p.is_file()})
    (sdk/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    archive=DIST/f'dyn-{version.removeprefix("dyn ")}-{platform.system().lower()}-{platform.machine()}.tar.gz'
    def normalize(info):
        info.uid=info.gid=0;info.uname=info.gname='';info.mtime=int(os.environ.get('SOURCE_DATE_EPOCH','0'));return info
    with archive.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as zipped:
        with tarfile.open(fileobj=zipped,mode='w') as tar:tar.add(sdk,arcname='dyn-sdk',filter=normalize)
    (DIST/(archive.name+'.sha256')).write_text(sha(archive)+'  '+archive.name+'\n')
    relocated=work/'relocated sdk';relocated.mkdir()
    with tarfile.open(archive) as tar:tar.extractall(relocated,filter='data')
    shutil.rmtree(work/'stage')
    installed=relocated/'dyn-sdk';env=dict(os.environ);env.pop('DYN_SDK',None);env['DYN_CACHE_DIR']=str(work/'cache')
    for name,digest in manifest['files'].items():
        if sha(installed/name)!=digest:raise RuntimeError('Installed hash mismatch: '+name)
    for mode in ([],['--release']):
        subprocess.run([str(installed/'bin/dyn'),'build',str(ROOT/'tests/smoke'),'--no-cache','--quiet','--output',str(work/'smoke'),*mode],cwd=work,env=env,check=True,timeout=60)
        subprocess.run([str(work/'smoke')],check=True,timeout=30)
    env['DYN'] = str(installed/'bin/dyn')
    subprocess.run([sys.executable,str(ROOT/'tests/stdlib-host.py')],env=env,check=True,timeout=180)
    (DIST/'package-validation.json').write_text(json.dumps(dict(status='passed',runtime_sources=runtime_sources,archive=archive.name,sha256=sha(archive),manifest=manifest),indent=2)+'\n')
    print('PASS packaged and relocated standalone SDK:',archive)
