#!/usr/bin/env python3
"""Independent behavioral evaluation for fresh-context Dyn coding trials."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[2]
BODIES={
'bounded-copy': '''data:[8]u8=[1,2,3,4,5,6,7,8]
expect(candidate.copy(data[1..6],data[..4]))
expect(data[1]==1 && data[2]==2 && data[4]==4 && data[5]==6)
expect(!candidate.copy(data[..1],data[2..4]) && data[0]==1)
expect(candidate.copy(data[..0],data[..0]))''',
'retained-name': '''a:[256]u8=[] b:[256]u8=[]
output:=mem.arena_from_buffer(a[..]) scratch:=mem.arena_from_buffer(b[..])
_ = mem.arena_push(&scratch,8,1)
mark:=mem.arena_mark(&scratch)
value:=candidate.save(&output,&scratch," \\tAda\\r\\n")
expect(strings.equal(value,"Ada") && mem.arena_mark(&scratch)==mark)
bytes:=mem.arena_push(&scratch,128,1)[..128]
for *byte in bytes { byte.*=88 }
expect(strings.equal(value,"Ada"))
empty:=candidate.save(&output,&scratch,"   ")
expect(#len(empty)==0)''',
'checked-sum': '''values:[3]u32=[4294967295,4294967295,1]
expected:u64=8589934591
expect(candidate.sum(values[..])==expected)
expect(candidate.sum(values[..0])==0)''',
'parse-port': '''expect(candidate.port("1")==1 && candidate.port("65535")==65535)
expect(candidate.port("00080")==80 && candidate.port("0")==0)
expect(candidate.port("65536")==0 && candidate.port("")==0)
expect(candidate.port("-1")==0 && candidate.port(" 80")==0 && candidate.port("80x")==0)
long:[1024]u8=[] for *byte in long { byte.*='9' }
expect(candidate.port(long[..])==0)
for *zero_byte in long { zero_byte.*='0' } long[1023]='8'
expect(candidate.port(long[..])==8)''',
'handle-copy': '''data:[4]u8=[] generations:[1]u32=[] words:[1]u64=[]
map:=slots.init(data[..],generations[..],words[..],4)
h:=slots.insert(&map,"good") saved:[5]u8=[9,9,9,9,9]
expect(!candidate.retain(&map,h,saved[..3]) && saved[0]==9)
expect(candidate.retain(&map,h,saved[..]) && saved[4]==9)
expect(slots.remove(&map,h)) _=slots.insert(&map,"next")
expect(strings.equal(saved[..4],"good"))
expect(!candidate.retain(&map,h,saved[..]) && saved[0]=='g')''',
'state-model': '''expect(candidate.amount(candidate.Status.Pending)==0)
expect(candidate.amount(candidate.Status.Complete(42))==42)
expect(candidate.amount(candidate.Status.Failed(-1))==0)''',
}


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--solutions',type=Path,default=ROOT/'build/ai-benchmark')
    p.add_argument('--dyn',default=os.environ.get('DYN',str(ROOT/'build/dyn')))
    p.add_argument('--output',type=Path,default=ROOT/'build/ai-benchmark/report.json')
    args=p.parse_args()
    rows=[]
    for task,body in BODIES.items():
        folder=args.solutions/task
        attempts=json.loads((folder/'attempts.json').read_text())
        row={'task':task,'solution_sha256':sha(folder/'main.dyn'),'attempts':attempts,
             'first_check_passed':bool(attempts and attempts[0]['exit_code']==0),'behavior':[]}
        with tempfile.TemporaryDirectory(prefix='dyn-ai-eval-') as directory:
            root=Path(directory); (root/'candidate').mkdir()
            shutil.copy2(folder/'main.dyn',root/'candidate/main.dyn')
            (root/'main.dyn').write_text('use "./candidate" candidate\nuse "std/mem"\nuse "std/strings"\nuse "std/container/slot_map" slots\n'
                'fn expect(ok:bool) { if !ok { #panic("independent behavioral check") } }\nfn main() {\n'+body+'\n}\n')
            for mode in ([],['--release']):
                result=subprocess.run([args.dyn,'build',str(root),'--no-cache','--quiet','--output',str(root/'program'),*mode],capture_output=True,text=True,timeout=60)
                run=None
                if result.returncode==0:
                    run=subprocess.run([str(root/'program')],capture_output=True,text=True,timeout=5)
                row['behavior'].append({'mode':'release' if mode else 'debug','compile_exit':result.returncode,
                    'run_exit':run.returncode if run else None,'stderr':result.stderr+(run.stderr if run else '')})
        row['passed']=all(r['compile_exit']==0 and r['run_exit']==0 for r in row['behavior'])
        rows.append(row)
    report={'schema':1,'scope':'Six fresh-context tasks; instruction-separated evaluator, not adversarially isolated. No comparison model or statistical generalization.',
            'compiler_sha256':sha(args.dyn),'task_manifest_sha256':sha(Path(__file__).parent/'tasks/manifest.json'),
            'first_check_passes':sum(r['first_check_passed'] for r in rows),'behavior_passes':sum(r['passed'] for r in rows),'tasks':rows}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('first_check_passes','behavior_passes')}))
    return 0 if all(r['passed'] for r in rows) else 1


if __name__=='__main__': raise SystemExit(main())
