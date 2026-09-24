#!/usr/bin/env python3
"""Build a relocatable SDK candidate, manifest, checksum, and unpacked smoke test."""
import argparse, gzip, hashlib, json, os, platform, re, shutil, subprocess, tarfile, tempfile
from pathlib import Path
COMPILER=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace', type=Path, default=COMPILER.parent)
parser.add_argument('--build', type=Path)
parser.add_argument('--grammar', type=Path, default=COMPILER.parent/'tree-sitter-dyn')
args=parser.parse_args()
ROOT=args.workspace.resolve()
BUILD=(args.build or (ROOT/'build' if (ROOT/'tests/run.sh').exists() else COMPILER/'build')).resolve()
DIST=BUILD/'dist'; DIST.mkdir(parents=True,exist_ok=True)
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
with tempfile.TemporaryDirectory(prefix='dyn-package-') as temporary:
    work=Path(temporary); stage=work/'stage'
    subprocess.run(['just','--justfile',str(COMPILER/'justfile'),'install'], env=dict(os.environ, BUILD=str(BUILD), TS_DIR=str(args.grammar.resolve()), DESTDIR=str(stage), PREFIX='/dyn-sdk'), check=True)
    sdk=stage/'dyn-sdk'
    if (ROOT/'docs').is_dir():
        shutil.copytree(ROOT/'docs',sdk/'docs',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(COMPILER/'README.md',sdk/'README.md')
    shutil.copy2(COMPILER/'LICENSE',sdk/'LICENSE')
    shutil.copy2(COMPILER/'THIRD_PARTY_NOTICES.md',sdk/'THIRD_PARTY_NOTICES.md')
    if (ROOT/'benchmarks/ai').is_dir():
        shutil.copytree(ROOT/'benchmarks/ai', sdk/'benchmarks/ai', ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    # Reference pages link to SDK source and checked-in example fixtures. Keep
    # those links usable after installation, without shipping compiler internals.
    for page in (sdk/'docs/reference').glob('*.md'):
        text = page.read_text().replace('](../../compiler/std/', '](../../share/dyn/').replace(
            '](../../compiler/vendor/', '](../../share/dyn/vendor/')
        for relative in re.findall(r'\]\(../../((?:tests|projects)/[^)#]+)(?:#[^)]*)?\)', text):
            example = sdk/relative
            example.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT/relative, example)
        page.write_text(text)
        for link in re.findall(r'\]\(([^)]+)\)', text):
            if link.startswith(('http:', 'https:', '#')): continue
            assert (page.parent/link.split('#',1)[0]).is_file(), (page,link)

    # The agent guide links to an executable tutorial; keep it usable after relocation.
    if (ROOT/'projects/memory-tour/main.dyn').is_file():
        tutorial = sdk/'projects/memory-tour'
        tutorial.mkdir(parents=True, exist_ok=True)
        for filename in ('main.dyn', 'README.md'):
            shutil.copy2(ROOT/'projects/memory-tour'/filename, tutorial/filename)
        if (ROOT/'projects/AGENTS.md').is_file():
            shutil.copy2(ROOT/'projects/AGENTS.md', sdk/'projects/AGENTS.md')

    dependency=subprocess.run(['ldd',str(sdk/'bin/dyn')],capture_output=True,text=True,check=True)
    assert 'not found' not in dependency.stdout,dependency.stdout
    version=subprocess.check_output([str(sdk/'bin/dyn'),'version'],text=True).strip()
    manifest=dict(version=version,host=platform.platform(),candidate=True,
        dependency_policy='System shared libraries required. This archive does not bundle LLVM, Tree-sitter or cross-link tools.',
        dependencies=[re.sub(r"\s*\(0x[0-9a-f]+\)", "", line).strip() for line in dependency.stdout.splitlines()],
        files={str(p.relative_to(sdk)):sha(p) for p in sorted(sdk.rglob('*')) if p.is_file()})
    (sdk/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    match=re.fullmatch(r'dyn ([0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?)',version)
    if not match: raise RuntimeError('Cannot derive safe archive version: '+version)
    archive=DIST/f'dyn-{match[1]}-{platform.system().lower()}-{platform.machine()}.tar.gz'
    def normalized(info):
        info.uid=info.gid=0;info.uname=info.gname='';info.mtime=int(os.environ.get('SOURCE_DATE_EPOCH','0'))
        return info
    with archive.open('wb') as raw, gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0) as compressed:
        with tarfile.open(fileobj=compressed,mode='w') as tar:
            tar.add(sdk,arcname='dyn-sdk',filter=normalized)
    (DIST/(archive.name+'.sha256')).write_text(f'{sha(archive)}  {archive.name}\n')
    unpack=work/'unpacked';unpack.mkdir()
    with tarfile.open(archive) as tar: tar.extractall(unpack,filter='data')
    # Relocated name contains spaces; remove staging installation before execution.
    relocated=work/'relocated sdk';(unpack/'dyn-sdk').rename(relocated);shutil.rmtree(stage)
    for relative,digest in manifest['files'].items(): assert sha(relocated/relative)==digest,relative
    dyn=str(relocated/'bin/dyn'); env=dict(os.environ)
    for tool in ('dyn-bind-vendors', 'dyn-raw-bind', 'dyn-browser-ffmpeg', 'dyn-query', 'dyn-sandbox'):
        subprocess.run([str(relocated/'bin'/tool), '--help'], env=env, check=True,
                       stdout=subprocess.DEVNULL, timeout=30)
    assert (relocated/'share/dyn/vendor/raw-bindings.json').is_file()
    env.pop('DYN_SDK',None);env['DYN_CACHE_DIR']=str(work/'cache')
    for fixture in [COMPILER/'tests/smoke', *([ROOT/'tests/owned-arenas', ROOT/'tests/sdk-unicode-text', ROOT/'tests/vendor-import'] if (ROOT/'tests/run.sh').exists() else [])]:
        subprocess.run([dyn,'check',str(fixture),'--quiet'],env=env,cwd=work,check=True,timeout=90)
    declarations = json.loads(subprocess.check_output(
        [dyn, 'docs', str(relocated/'share/dyn/container/slot_map'), '--json'],
        env=env, text=True, timeout=30))
    assert declarations['analysis'] == 'syntax-only'
    assert any(d['name'] == 'copy_into' for f in declarations['files'] for d in f['declarations'])
    if (relocated/'projects/memory-tour/main.dyn').is_file():
        tutorial_output = work/'memory-tour'
        subprocess.run([dyn, 'build', str(relocated/'projects/memory-tour'), '--release',
                        '--quiet', '--no-cache', '--output', str(tutorial_output)],
                       env=env, cwd=work, check=True, timeout=90)
        subprocess.run([str(tutorial_output)], check=True, stdout=subprocess.DEVNULL, timeout=30)
    output=work/'program'
    subprocess.run([dyn,'build',str(COMPILER/'tests/smoke'),'--release','--no-cache','--quiet','--output',str(output)],env=env,cwd=work,check=True,timeout=90)
    subprocess.run([str(output)],check=True,timeout=30)
    (DIST/'package-validation.json').write_text(json.dumps(dict(archive=archive.name,sha256=sha(archive),status='passed',manifest=manifest),indent=2)+'\n')
    print(f'PASS packaged and relocated SDK: {archive}')
