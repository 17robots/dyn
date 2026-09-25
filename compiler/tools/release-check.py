#!/usr/bin/env python3
"""Run workspace release gates and bind their evidence to exact source/artifacts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'build/release-check'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def source_hash():
    digest = hashlib.sha256()
    for name in ('compiler', 'tree-sitter-dyn', 'projects', 'tests', 'tools', 'benchmarks', 'docs', '.github', '.devcontainer', 'playground', 'zed-dyn'):
        for directory, dirs, files in os.walk(ROOT / name):
            dirs[:] = sorted(d for d in dirs if d not in ('build', '.git', '.jj', 'node_modules', '__pycache__', 'target', 'dist'))
            for file in sorted(files):
                path = Path(directory) / file
                if path.suffix not in ('.c', '.h', '.S', '.dyn', '.py', '.sh', '.lua', '.js', '.json', '.yaml', '.yml', '.md', '.toml', '.scm', '.txt', '.lock', '.wasm', '.just', '.in', '.html', '.mjs', '.cjs', '.css') and file not in ('justfile', 'Dockerfile', 'LICENSE', '.tree-sitter-version'):
                    continue
                digest.update(str(path.relative_to(ROOT)).encode() + b'\0' + path.read_bytes() + b'\0')
    digest.update((ROOT/'justfile').read_bytes())
    if (ROOT/'LICENSE').is_file(): digest.update((ROOT/'LICENSE').read_bytes())
    return digest.hexdigest()

def environment():
    env = dict(os.environ)
    prefix = ROOT/'build/vendor-deps/install'
    for key, suffix in (('PKG_CONFIG_PATH','lib/pkgconfig'), ('DYN_LIBRARY_PATH','lib'), ('LD_LIBRARY_PATH','lib')):
        env[key] = str(prefix/suffix) + (os.pathsep + env[key] if env.get(key) else '')
    env['DYN'] = str(ROOT/'build/dyn-release')
    env['DYN_SDK'] = str(ROOT/'compiler')
    env['DYN_REQUIRE_ALL'] = '1'
    return env

def preflight(env, baseline):
    policy = json.loads((ROOT/'docs/release/toolchain.json').read_text())
    rows, failures = {}, []
    def record(name, command):
        try:
            result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30, check=True)
            rows[name] = (result.stdout or result.stderr).strip()
        except (OSError, subprocess.SubprocessError) as error:
            failures.append(f'{name}: {error}')
        return rows.get(name, '')
    if (platform.system(), platform.machine()) != ('Linux', 'x86_64'):
        failures.append('Release host currently requires Linux x86-64')
    for name, cmd in [('cc', shlex.split(env.get('CC','cc'))+['--version']), ('clang',shlex.split(env.get('CLANG','clang'))+['--version']), ('just',['just','--version']), ('tree-sitter',['tree-sitter','--version']), ('zig',['zig','version']), ('nvim',['nvim','--version']), ('wasm-ld',['wasm-ld','--version']), ('node',['node','--version'])]:
        record(name, cmd)
    packages = ['libavformat','libavcodec','libavutil','libswscale','libswresample','libavfilter','libavdevice','tree-sitter','openssl','sqlite3','libzstd','sdl3','sdl3-image','sdl3-ttf','tree-sitter-c','libpcre2-8','lua5.4','libarchive','libcurl','vulkan','liblz4','dyn-cgltf','dyn-box2d','dyn-microui','dyn-enet','dyn-miniaudio','sdl3-mixer','dyn-stb','dyn-microui-sdl3']
    for package in packages:
        record('provider:'+package, ['pkg-config','--modversion',package])
    if not shutil.which('gdb'): failures.append('gdb is required for debug-info tests')
    if not (env.get('DYN_TEST_FONT') and Path(env['DYN_TEST_FONT']).is_file()) and not list(Path('/usr/share/fonts').rglob('DejaVuSans.ttf')):
        failures.append('DejaVuSans.ttf or DYN_TEST_FONT required')
    match = re.search(r'NVIM v(\d+)\.(\d+)', rows.get('nvim',''))
    if not match or tuple(map(int,match.groups())) < (0,11): failures.append('Neovim 0.11+ required; editor checks may not skip')
    generator = policy['baseline']['tree_sitter_generator']
    if not rows.get('tree-sitter','').startswith('tree-sitter '+generator): failures.append('Wrong grammar generator; expected '+generator)
    if baseline:
        llvm = record('llvm-config', [env.get('LLVM_CONFIG','llvm-config'),'--version'])
        if llvm.split('.')[0] != str(policy['baseline']['llvm_major']): failures.append('LLVM baseline mismatch')
        if rows.get('provider:tree-sitter') != policy['baseline']['tree_sitter_runtime']: failures.append('Tree-sitter runtime baseline mismatch')
        if rows.get('zig') != policy['baseline']['zig']: failures.append('Zig baseline mismatch')
    return dict(host=platform.platform(), versions=rows, failures=failures, baseline_requested=baseline)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', action='store_true', help='Require the release CI toolchain baseline')
    parser.add_argument('--preflight', action='store_true', help='Only inspect dependencies; never qualifies a candidate')
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--only', action='append', help='Run named stages for development; report remains partial')
    parser.add_argument('--performance-baseline', type=Path, help='Same-machine scaling report for regression comparison')
    args = parser.parse_args()
    if os.environ.get('BUILD') and Path(os.environ['BUILD']).resolve() != ROOT/'build':
        parser.error('The workspace release suites require BUILD=build')
    just = ['just','--justfile',str(ROOT/'justfile')]
    performance = [sys.executable,'benchmarks/compiler-scaling.py','--verify','--output','build/readiness/scaling.json']
    if args.performance_baseline: performance += ['--baseline',str(args.performance_baseline.resolve())]
    stages = [
        ('release-tools', [sys.executable,'tests/release-tools.py']),
        ('build', just+['perf-compiler']),
        ('quality', just+['quality-c']),
        ('libraries', just+['test-libraries']),
        ('preview', just+['test-preview']),
        ('wasm-browser', [sys.executable,'tests/wasm-browser.py']),
        ('wasm-memory', [sys.executable,'tests/wasm-memory.py']),
        ('wasi', [sys.executable,'tests/wasi.py']),
        ('browser-ffmpeg', [sys.executable,'tests/browser-ffmpeg.py']),
        ('providers', [sys.executable,'tests/vendor-packages.py','--require-all']),
        ('vendor-extra', [sys.executable,'tests/vendor-extra.py','--require-all']),
        ('vendor-bindings', [sys.executable,'compiler/tools/bind-vendors.py']),
        ('vendor-raw', [sys.executable,'tests/vendor-raw.py']),
        ('vendor-setup', [sys.executable,'tests/vendor-setup.py']),
        ('vendor-sanitize', [sys.executable,'tests/vendor-sanitize.py']),
        ('readiness', just+['test-readiness']),
        ('projects', just+['test-projects']),
        ('editor', [sys.executable,'tests/neovim.py']),
        ('sdl', [sys.executable,'tests/sdl3-applications.py']),
        ('components', [sys.executable,'tests/just-components.py']),
        ('performance', performance),
        ('compile-phases', [sys.executable,'benchmarks/compiler-phases.py','--output','build/readiness/compiler-phases.json']),
        ('compile-cache', ['sh','benchmarks/compile/run.sh','7','--check']),
        ('large-functions', [sys.executable,'benchmarks/large-function.py','--verify','--output','build/readiness/large-functions.json']),
        ('member-work', [sys.executable,'benchmarks/member-work.py','--verify','--output','build/readiness/member-work.json']),
        ('release-contracts', ['sh','tests/release-gate.sh']),
        ('packages', just+['package-sdk','package-grammar','package-projects']),
    ]
    if args.list:
        for name, command in stages: print(name+': '+shlex.join(command))
        return 0
    if args.only and set(args.only)-{name for name,_ in stages}: parser.error('unknown --only stage')
    OUT.mkdir(parents=True, exist_ok=True)
    # Shared fixtures/build outputs mean simultaneous release checks are invalid.
    import fcntl
    with (OUT/'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # A failed rerun must never leave an older passing bundle beside its report.
        if (OUT/'artifacts').exists(): shutil.rmtree(OUT/'artifacts')
        (OUT/'RELEASE-NOTES.md').unlink(missing_ok=True)
        env = environment()
        report = dict(status='running',scope='Linux x86-64 developer preview', stages=[], preflight=preflight(env,args.baseline), source_sha256=source_hash(), started_unix=time.time(), external_evidence=['Native Windows/macOS/ARM execution', 'Actual GPU/audio hardware', 'Published editor grammar and installed extension', 'Long-term user experience'])
        def save(): (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        save()
        if report['preflight']['failures'] and not args.only:
            report['status']='blocked'; save()
            print('\n'.join(report['preflight']['failures']),file=sys.stderr)
            return 1
        if args.preflight:
            report['status']='preflight-only'; save(); print(json.dumps(report['preflight'],indent=2)); return 0
        try:
            for name, command in stages:
                if args.only and name not in args.only: continue
                print('RUN '+name,flush=True)
                start=time.monotonic()
                with (OUT/(name+'.log')).open('w') as log:
                    result=subprocess.run(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=3600)
                report['stages'].append(dict(name=name,command=command,status='passed' if result.returncode==0 else 'failed',returncode=result.returncode,seconds=time.monotonic()-start,log='build/release-check/'+name+'.log'))
                save()
                if result.returncode: raise RuntimeError(f'{name} failed; see {OUT/name}.log')
            if source_hash()!=report['source_sha256']: raise RuntimeError('Source changed during validation; rerun with a frozen candidate')
            report['status']='partial' if args.only else 'passed'
            if not args.only:
                sdk = json.loads((ROOT/'build/dist/package-validation.json').read_text())
                artifacts = [ROOT/'build/dist'/sdk['archive'], ROOT/'build/dist/dyn-grammar-candidate.tar.gz', ROOT/'build/projects/dist/dyn-projects-candidate.tar.gz']
                destination=OUT/'artifacts'
                if destination.exists(): shutil.rmtree(destination)
                destination.mkdir()
                stem=artifacts[0].name.removesuffix('.tar.gz')
                copies=[]
                for index, source in enumerate(artifacts):
                    name=source.name if index==0 else stem+('-grammar' if index==1 else '-projects')+'.tar.gz'
                    target=destination/name
                    shutil.copy2(source,target);copies.append(target)
                report['artifacts']={str(p.relative_to(ROOT)):sha(p) for p in copies}
                (destination/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in copies))
                report['compiler_sha256']=sha(ROOT/'build/dyn-release')
                notes = '# Dyn Linux x86-64 developer preview\n\nAll required local gates passed for this source and these archives.\n\n'
                notes += 'Source SHA-256: `'+report['source_sha256']+'`\n\n'
                notes += '\n'.join('- `'+name+'`: `'+digest+'`' for name,digest in report['artifacts'].items())+'\n\n'
                notes += 'See docs/stability.md and docs/release/readiness.md for compatibility and experimental scope. Native platform, hardware and editor publication evidence remain separate.\n'
                (OUT/'RELEASE-NOTES.md').write_text(notes)
        except BaseException as error:
            report['status']='failed';report['error']=str(error);raise
        finally:
            report['finished_unix']=time.time();save()
        print('Release check: '+report['status']+'; '+str(OUT/'report.json'))
    return 0

if __name__=='__main__': sys.exit(main())
