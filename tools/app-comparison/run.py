#!/usr/bin/env python3
"""Build, independently check, then serially measure small real applications.

No compiler/std edits or network dependency downloads. Linux execution only.
"""
import argparse,concurrent.futures,signal,hashlib,http.client,json,os,platform,select,shutil,socket,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];SRC=Path(__file__).resolve().parent
MAX=2**53-1
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--output',type=Path,default=ROOT/'build/app-comparison-20261024')
parser.add_argument('--rounds',type=int,default=9)
parser.add_argument('--http-rounds',type=int,default=5)
parser.add_argument('--records',type=int,default=60000)
parser.add_argument('--files',type=int,default=1024)
parser.add_argument('--check-only',action='store_true')
a=parser.parse_args();OUT=a.output.resolve();OUT.mkdir(parents=True,exist_ok=True)
ENV=dict(os.environ,DYN_SDK=str(ROOT),GOMAXPROCS='1',GOAMD64='v1',GOTOOLCHAIN='local')
for k in ('DYN_NO_SSA','LD_PRELOAD'):ENV.pop(k,None)
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def terminate(p):
    try:os.killpg(p.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    p.wait(timeout=5)
def run(cmd,timeout=120,**kw):
    command=list(map(str,cmd))
    p=subprocess.Popen(command,env=ENV,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True,**kw)
    try:stdout,stderr=p.communicate(timeout=timeout)
    except BaseException:
        terminate(p);p.communicate();raise
    if p.returncode:raise RuntimeError((command,p.returncode,stdout[-2000:],stderr[-2000:]))
    return subprocess.CompletedProcess(command,p.returncode,stdout,stderr)
report={'schema':1,'host':platform.platform(),'cpu_model':next(x.split(':',1)[1].strip() for x in Path('/proc/cpuinfo').read_text().splitlines() if x.startswith('model name')),'compiler_sha256':digest(ROOT/'build/dyn-release'),'cpu':2,'client_cpus':[4,5,6,7],'scope':'warm-filesystem CLI startup+I/O; std/library application ports; local HTTP single CPU, one and four clients; no language-wide ranking','settings':vars(a)|{'output':str(OUT)},'builds':{},'correctness':[],'cli':{},'http':{}}
def save():
    (OUT/'results.json').write_text(json.dumps(report,indent=2)+'\n')
def recordcheck(label):report['correctness'].append(label);save()
def sources():return {p.name:digest(p) for p in SRC.iterdir() if p.is_file() and p.suffix in ('.dyn','.c','.rs','.go','.js','.py','.toml','.lock','.md')}
report['sources']=sources()
# Build all application variants before timing. Cargo dependencies are available offline.
commands={}
clang=str(Path('/usr/bin/clang')) if Path('/usr/bin/clang').exists() else shutil.which('clang');gcc=shutil.which('gcc');rustc=shutil.which('rustc');go=shutil.which('go');node=shutil.which('node')
needed={'clang':clang,'gcc':gcc,'rustc':rustc,'cargo':shutil.which('cargo'),'go':go,'node':node,'taskset':shutil.which('taskset')}
if not all(needed.values()):raise RuntimeError(('missing prerequisites',needed))
ccflags=run(['pkg-config','--cflags','--libs','yyjson']).stdout.decode().split()
builds={
 'dyn':[ROOT/'build/dyn-release','build',SRC,'--release','--opt-level','3','--cpu','generic','--no-cache','--quiet','--output',OUT/'dyn-app'],
 'gcc':[gcc,'-O3','-march=x86-64','-std=c11','-Wall','-Wextra','-Werror',SRC/'main.c',*ccflags,'-lm','-o',OUT/'gcc-app'],
 'clang':[clang,'-O3','-march=x86-64','-std=c11','-Wall','-Wextra','-Werror',SRC/'main.c',*ccflags,'-lm','-o',OUT/'clang-app'],
 'rust':[shutil.which('cargo'),'build','--offline','--release','--manifest-path',SRC/'Cargo.toml','--target-dir',OUT/'rust-target'],
 'go':[go,'build','-o',OUT/'go-app',SRC/'main.go']}
for lang,cmd in builds.items():
    start=time.perf_counter();p=run(cmd);elapsed=time.perf_counter()-start
    (OUT/f'{lang}-build.log').write_bytes(p.stdout+p.stderr)
    commands[lang]=[str(OUT/'rust-target/release/rust-app')] if lang=='rust' else [str(OUT/f'{lang}-app')]
    binary=Path(commands[lang][0]);report['builds'][lang]={'command':list(map(str,cmd)),'seconds_observed':elapsed,'sha256':digest(binary),'executable_bytes':binary.stat().st_size}
commands['node']=[node,str(SRC/'main.js')];commands['python']=[sys.executable,str(SRC/'main.py')]
report['versions']={k:run(v).stdout.decode().strip().splitlines()[0] for k,v in {'dyn':[ROOT/'build/dyn-release','version'],'gcc':[gcc,'--version'],'clang':[clang,'--version'],'rust':[rustc,'--version'],'go':[go,'version'],'node':[node,'--version'],'python':[sys.executable,'--version'],'yyjson':['pkg-config','--modversion','yyjson']}.items()}
assert report['sources']==sources(),'sources changed during builds'
# Corpus oracle depends directly on generator values, never implementation output.
def empty():return {'records':0,'bytes':0,'latency_us':0,'errors':0,'services':[[0]*4 for _ in range(16)]}
def add_expected(s,obj):
    i=int(obj['service'][3:]);values=[1,int(obj['bytes']),int(obj['latency_us']),int(obj['status']>=500)]
    for key,n in zip(('records','bytes','latency_us','errors'),values):s[key]+=n
    for k,n in enumerate(values):s['services'][i][k]+=n
log=OUT/'events.jsonl';expected=empty();http_records=[]
with log.open('wb') as f:
    for i in range(a.records):
        obj={'id':i,'service':f'svc{(i*7)%16:02}','status':503 if i%17==0 else (404 if i%11==0 else 200),'bytes':(i*7919)%65536,'latency_us':(i*131)%250000,'path':f'/api/v1/items/{i%1000}?page={i%17}','message':'request "done"\t café snowman ☃','tags':['edge',f'zone-{i%8}'],'context':{'cached':i%3==0,'attempt':i%4+1}}
        add_expected(expected,obj)
        if i<64:http_records.append(obj)
        f.write(json.dumps(obj,ensure_ascii=i%3==0,separators=(',',':')).encode())
        if i!=a.records-1:f.write(b'\n')
        if i%997==0:f.write(b'\n')
searchdir=OUT/'documents'
if searchdir.exists():shutil.rmtree(searchdir)
searchdir.mkdir();search_expected=dict(files=0,bytes=0,lines=0,matching_lines=0,matching_files=0)
for i in range(a.files):
    folder=searchdir/f'project-{i%32:02}'/'src';folder.mkdir(parents=True,exist_ok=True)
    lines=[];matches=0
    for j in range(256):
        bad=i%9!=0 and (i*19+j*7)%41==0
        prefix=b'ERROR' if bad else b'INFO '
        lines.append(prefix+f' module={i%32} item={j} '.encode()+bytes([97+(i+j)%26])*220)
        matches+=bad
    content=b'\n'.join(lines)+(b'\n' if i%2 else b'')
    (folder/f'unit-{i:04}.txt').write_bytes(content)
    search_expected['files']+=1;search_expected['bytes']+=len(content);search_expected['lines']+=len(lines);search_expected['matching_lines']+=matches;search_expected['matching_files']+=matches>0
    if i%16==0:(folder/f'ignored-{i}.bin').write_bytes(b'ERROR\n'*20)
(searchdir/'link.txt').symlink_to(searchdir/'project-00/src/unit-0000.txt')
(searchdir/'link-directory').symlink_to(searchdir/'project-00',target_is_directory=True)
(OUT/'expected.json').write_text(json.dumps({'report':expected,'search':search_expected},indent=2)+'\n')
report['inputs']={'report':{'path':str(log),'bytes':log.stat().st_size,'records':a.records,'sha256':digest(log)},'search':{'path':str(searchdir),**search_expected,'sha256':hashlib.sha256(''.join(str(p.relative_to(searchdir))+digest(p) for p in sorted(searchdir.rglob('*')) if p.is_file() and not p.is_symlink()).encode()).hexdigest()}}
# Correctness small fixtures cover bytes, escaped keys/values, semantic integers and schema failures.
fixture=OUT/'checks';fixture.mkdir(exist_ok=True)
valid=(b'{"serv\\u0069ce":"svc\\u0030\\u0031","status":500.0,"bytes":2e1,"latency_us":-0,"other":{"a":[null,true,"\\uD83D\\uDE00"]}}\n\n'
       b'{"service":"svc15","status":200,"bytes":1,"latency_us":2}')
vpath=fixture/'valid.jsonl';vpath.write_bytes(valid);valid_expected=empty()
for o in ({'service':'svc01','status':500,'bytes':20,'latency_us':0},{'service':'svc15','status':200,'bytes':1,'latency_us':2}):add_expected(valid_expected,o)
bad=[b'{',b'[]',b'null',b'{"service":"svc00","status":true,"bytes":1,"latency_us":2}',b'{"service":"svc16","status":200,"bytes":1,"latency_us":2}',b'{"service":"svc00","status":200,"bytes":-1,"latency_us":2}',b'{"service":"svc00","status":200.5,"bytes":1,"latency_us":2}',b'{"service":"svc00","status":600,"bytes":1,"latency_us":2}',b'{"service":"svc00","status":200,"bytes":9007199254740992,"latency_us":2}',b'{"service":"svc00","status":200,"bytes":1,"latency_us":2,"extra":NaN}',b'{"service":"svc00","status":200,"bytes":1}']
bad.append(b'{"service":"svc00","status":200,"bytes":9007199254740991,"latency_us":0}\n{"service":"svc00","status":200,"bytes":1,"latency_us":0}')
small=fixture/'tree';small.mkdir(exist_ok=True)
for p,content in [('a.txt',b'ERROR\n\n\xffERROR'),('b.txt',b''),('c.txt',b'abc\nERROR ERROR\n'),('skip.bin',b'ERROR')]: (small/p).write_bytes(content)
if not (small/'alias.txt').exists():(small/'alias.txt').symlink_to(small/'a.txt')
small_expected={'files':3,'bytes':len(b'ERROR\n\n\xffERROR')+len(b'abc\nERROR ERROR\n'),'lines':5,'matching_lines':3,'matching_files':2}
for lang,cmd in commands.items():
    for mode,path,want in [('report',vpath,valid_expected),('search',small,small_expected),('report',log,expected),('search',searchdir,search_expected)]:
        p=run([*cmd,mode,path]);assert json.loads(p.stdout)==want,(lang,mode,p.stdout,want)
    for i,data in enumerate(bad):
        p=fixture/f'bad-{i}.jsonl';p.write_bytes(data);v=subprocess.run([*cmd,'report',str(p)],env=ENV,capture_output=True,timeout=30)
        assert v.returncode!=0 and not v.stdout,(lang,'accepted invalid',i,v.stdout)
    with open('/dev/full','wb') as full:
        v=subprocess.run([*cmd,'report',str(vpath)],env=ENV,stdout=full,stderr=subprocess.PIPE,timeout=30)
    assert v.returncode!=0,(lang,'lost stdout failure')
    recordcheck(f'{lang}: full report/search oracles, escaped schema, byte fixtures, {len(bad)} negatives, stdout failure')
    print('CHECK CLI',lang,flush=True)
# Server helper pins only server; clients retain a separate CPU set.
http_langs=('dyn','go','node','python')
def start_server(lang,timeout=15):
    err=(OUT/f'{lang}-server.log').open('ab');t=time.perf_counter()
    p=subprocess.Popen(['taskset','-c','2',*commands[lang],'serve'],env=ENV,stdout=subprocess.PIPE,stderr=err,start_new_session=True)
    try:
        line=bytearray()
        while not line.endswith(b'\n'):
            remaining=timeout-(time.perf_counter()-t)
            if remaining<=0 or not select.select([p.stdout],[],[],remaining)[0]:raise RuntimeError((lang,'startup timeout'))
            part=os.read(p.stdout.fileno(),1)
            if not part or len(line)>100:raise RuntimeError((lang,'invalid startup line',line))
            line.extend(part)
        text=line.decode().strip()
        if not text.startswith('port '):raise RuntimeError((lang,'invalid startup line',text))
        port=int(text.split()[1])
        if not 0<port<65536:raise RuntimeError((lang,'invalid port',port))
        return p,err,port,time.perf_counter()-t
    except BaseException:
        terminate(p);p.stdout.close();err.close();raise
def request(port,method,path,body=b''):
    c=http.client.HTTPConnection('127.0.0.1',port,timeout=15)
    try:
        c.request(method,path,body=body,headers={'Connection':'close','Content-Type':'application/json'})
        r=c.getresponse();return r.status,r.read()
    finally:c.close()
def stop_server(p,err,port):
    try:
        status,_=request(port,'POST','/quit');assert status==200,status
        assert p.wait(timeout=10)==0,p.returncode
    finally:
        if p.poll() is None:terminate(p)
        p.stdout.close();err.close()
http_expected=empty()
for o in http_records:add_expected(http_expected,o)
payload=json.dumps(http_records,ensure_ascii=False,separators=(',',':')).encode()
report['http_input']={'records':len(http_records),'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
for lang in http_langs:
    p,err,port,_=start_server(lang)
    try:
        assert request(port,'GET','/health')==(200,b'ok\n')
        assert request(port,'GET','/missing')[0]==404
        status,body=request(port,'POST','/summarize',payload);assert status==200 and json.loads(body)==http_expected,(lang,status,body[:1000])
        for body in (b'{',b'{}',b'[{"service":"svc00","status":200,"bytes":1,"latency_us":1,"extra":NaN}]',b'[]'+b' '*(1024*1024-1)):
            assert request(port,'POST','/summarize',body)[0]==400,(lang,'accepted invalid HTTP')
    finally:stop_server(p,err,port)
    recordcheck(f'{lang}: HTTP health/404/body/schema/malformed/1MiB limit/clean quit');print('CHECK HTTP',lang,flush=True)
if a.check_only:
    assert report['sources']==sources(),'sources changed during checks'
    save();print('CHECKS PASS');raise SystemExit(0)
os.sched_setaffinity(0,{4,5,6,7})
peak=OUT/'peak'
peak_source_hash=digest(ROOT/'tools/compare/peak.c')
run(['cc','-O2',ROOT/'tools/compare/peak.c','-o',peak])
assert peak_source_hash==digest(ROOT/'tools/compare/peak.c'),'peak source changed during build'
report['peak_helper']={'source_sha256':peak_source_hash,'binary_sha256':digest(peak),'scope':'wait4/RUSAGE_CHILDREN maximum individual-process RSS, rounded to 0.1 MiB'}
for mode,path,want in [('report',log,expected),('search',searchdir,search_expected)]:
    samples={k:[] for k in commands};keys=list(commands)
    for i in range(a.rounds+2):
        order=keys[i%len(keys):]+keys[:i%len(keys)]
        if (i//len(keys))%2:order.reverse()
        for lang in order:
            p=run([peak,'taskset','-c','2',*commands[lang],mode,path],timeout=60)
            assert json.loads(p.stdout)==want,(mode,lang,p.stdout)
            metric=json.loads(p.stderr.decode().splitlines()[-1])
            if i>=2:samples[lang].append(metric)
    report['cli'][mode]={'samples':samples,'medians':{k:{m:statistics.median(x[m] for x in v) for m in ('seconds','rss_mib')} for k,v in samples.items()}}
    save();print('TIME CLI',mode,report['cli'][mode]['medians'],flush=True)
def percent(v,p):return sorted(v)[max(0,min(len(v)-1,int(len(v)*p)-1))]
for round in range(a.http_rounds):
    order=list(http_langs);order=order[round%4:]+order[:round%4]
    for lang in order:
        p,err,port,startup=start_server(lang)
        try:
            def one():
                t=time.perf_counter();status,body=request(port,'POST','/summarize',payload);elapsed=time.perf_counter()-t
                assert status==200 and json.loads(body)==http_expected,(lang,status,body[:1000]);return elapsed
            for _ in range(100):one()
            latency=[one() for _ in range(100)]
            def batch(_):return [one() for _ in range(75)]
            t=time.perf_counter()
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:parallel=sum(pool.map(batch,range(4)),[])
            elapsed=time.perf_counter()-t
            status=Path(f'/proc/{p.pid}/status').read_text();hwm=int(next(line.split()[1] for line in status.splitlines() if line.startswith('VmHWM:')))
            sample={'startup_seconds':startup,'single_median_seconds':statistics.median(latency),'single_p95_seconds':percent(latency,.95),'four_requests_per_second':300/elapsed,'four_p95_seconds':percent(parallel,.95),'peak_rss_kib':hwm,'validated_requests':500}
            report['http'].setdefault(lang,[]).append(sample);save();print('TIME HTTP',round,lang,sample,flush=True)
        finally:stop_server(p,err,port)
report['sources_after']={p.name:digest(p) for p in SRC.iterdir() if p.is_file() and p.name in report['sources']}
assert report['sources']==report['sources_after'],'benchmark sources changed during qualification'
assert peak_source_hash==digest(ROOT/'tools/compare/peak.c'),'peak source changed during qualification'
assert report['compiler_sha256']==digest(ROOT/'build/dyn-release'),'Dyn compiler changed during qualification'
save();print('APPLICATION COMPARISON PASS',flush=True)
