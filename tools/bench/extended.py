#!/usr/bin/env python3
"""Four native language ports. Prepare/check first; time only in a separate serial window.

Map and UTF-8 use matched explicit algorithms; sorting and allocation intentionally
compare library/allocator choices. Whole-process times include initialization,
startup and shutdown. These are bounded kernels, not application benchmarks.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
MASK = (1 << 64)-1
SCOPES = {
    'sort': 'library comparison: Dyn heapsort, C qsort, Rust sort_unstable, Go slices.Sort; same u32 keys/checksum',
    'map': 'matched linear probing, multiplicative hash, 50% maximum occupancy; explicit arrays, no standard maps',
    'utf8': 'matched generated valid UTF-8 and explicit scalar decoder; no malformed-input claim',
    'allocate': 'allocator/library comparison: Dyn arena bulk release; C malloc/free; Rust Box; Go heap slices + GC; 64-byte retained blocks',
}
C = r'''
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static uint32_t next(uint32_t *x){return *x=*x*1664525u+1013904223u;}
static int compare(const void*a,const void*b){uint32_t x=*(const uint32_t*)a,y=*(const uint32_t*)b;return(x>y)-(x<y);}
int main(int argc,char**argv){if(argc!=5)return 2;char *mode=argv[1];size_t n=strtoull(argv[2],0,10),rounds=strtoull(argv[3],0,10);uint32_t seed=strtoul(argv[4],0,10);uint64_t sum=0;
if(!strcmp(mode,"sort")){uint32_t*a=malloc(n*4);if(!a)return 3;for(size_t r=0;r<rounds;r++){uint32_t x=seed+(uint32_t)r;for(size_t i=0;i<n;i++)a[i]=next(&x);qsort(a,n,4,compare);for(size_t i=0;i<n;i++)sum+=(uint64_t)a[i]*(i+1);}free(a);}
else if(!strcmp(mode,"map")){size_t cap=1;while(cap<n*2)cap*=2;uint32_t*k=calloc(cap,4),*v=calloc(cap,4),*input=malloc(n*4);if(!k||!v||!input)return 3;for(size_t r=0;r<rounds;r++){memset(k,0,cap*4);memset(v,0,cap*4);uint32_t x=seed+(uint32_t)r;for(size_t i=0;i<n;i++){uint32_t key=1+(next(&x)>>8)%(n*8);input[i]=key;size_t p=(uint32_t)(key*2654435761u)&(cap-1);while(k[p]&&k[p]!=key)p=(p+1)&(cap-1);k[p]=key;v[p]++;}for(size_t p=0;p<cap;p++)sum+=(uint64_t)k[p]*v[p];for(size_t i=0;i<n;i++){uint32_t key=input[i];size_t p=(uint32_t)(key*2654435761u)&(cap-1);while(k[p]!=key)p=(p+1)&(cap-1);sum+=(uint64_t)key*v[p];}}free(k);free(v);free(input);}
else if(!strcmp(mode,"utf8")){unsigned char*a=malloc(n*4);if(!a)return 3;size_t used=0;uint32_t x=seed;for(size_t i=0;i<n;i++){uint32_t c=next(&x)%0x10f800;if(c>=0xd800)c+=0x800;if(c<128)a[used++]=c;else if(c<2048){a[used++]=192|(c>>6);a[used++]=128|(c&63);}else if(c<65536){a[used++]=224|(c>>12);a[used++]=128|((c>>6)&63);a[used++]=128|(c&63);}else{a[used++]=240|(c>>18);a[used++]=128|((c>>12)&63);a[used++]=128|((c>>6)&63);a[used++]=128|(c&63);}}for(size_t r=0;r<rounds;r++){size_t i=0;while(i<used){uint32_t c=a[i++];unsigned more=0;if(c>=240){c&=7;more=3;}else if(c>=224){c&=15;more=2;}else if(c>=192){c&=31;more=1;}while(more--){c=(c<<6)|(a[i++]&63);}sum+=c;}}free(a);}
else if(!strcmp(mode,"allocate")){uint64_t**a=malloc(n*sizeof(*a));if(!a)return 3;for(size_t r=0;r<rounds;r++){uint32_t x=seed+(uint32_t)r;for(size_t i=0;i<n;i++){a[i]=calloc(8,8);if(!a[i])return 3;a[i][0]=next(&x);a[i][7]=next(&x);}for(size_t i=0;i<n;i++){sum+=a[i][0]+a[i][7];free(a[i]);}}free(a);}else return 2;printf("%llu\n",(unsigned long long)sum);return 0;}
'''
RUST = r'''
fn next(x:&mut u32)->u32{*x=x.wrapping_mul(1664525).wrapping_add(1013904223);*x}
fn main(){let a:Vec<String>=std::env::args().collect();let mode=&a[1];let n:usize=a[2].parse().unwrap();let rounds:usize=a[3].parse().unwrap();let seed:u32=a[4].parse().unwrap();let mut sum=0u64;
match mode.as_str(){
"sort"=>{let mut v=vec![0u32;n];for r in 0..rounds{let mut x=seed.wrapping_add(r as u32);for y in &mut v{*y=next(&mut x);}v.sort_unstable();for(i,y)in v.iter().enumerate(){sum=sum.wrapping_add(*y as u64*(i+1)as u64);}}},
"map"=>{let cap=(n*2).next_power_of_two();let mut k=vec![0u32;cap];let mut v=vec![0u32;cap];let mut input=vec![0u32;n];for r in 0..rounds{k.fill(0);v.fill(0);let mut x=seed.wrapping_add(r as u32);for key in &mut input{*key=1+(next(&mut x)>>8)%(n as u32*8);let mut p=key.wrapping_mul(2654435761)as usize&(cap-1);while k[p]!=0&&k[p]!=*key{p=(p+1)&(cap-1);}k[p]=*key;v[p]+=1;}for p in 0..cap{sum=sum.wrapping_add(k[p]as u64*v[p]as u64);}for key in &input{let mut p=key.wrapping_mul(2654435761)as usize&(cap-1);while k[p]!=*key{p=(p+1)&(cap-1);}sum=sum.wrapping_add(*key as u64*v[p]as u64);}}},
"utf8"=>{let mut v=Vec::with_capacity(n*4);let mut x=seed;for _ in 0..n{let mut c=next(&mut x)%0x10f800;if c>=0xd800{c+=0x800;}if c<128{v.push(c as u8);}else if c<2048{v.push((192|(c>>6))as u8);v.push((128|(c&63))as u8);}else if c<65536{v.push((224|(c>>12))as u8);v.push((128|((c>>6)&63))as u8);v.push((128|(c&63))as u8);}else{v.push((240|(c>>18))as u8);v.push((128|((c>>12)&63))as u8);v.push((128|((c>>6)&63))as u8);v.push((128|(c&63))as u8);}}for _ in 0..rounds{let mut i=0;while i<v.len(){let mut c=v[i]as u32;i+=1;let more;if c>=240{c&=7;more=3;}else if c>=224{c&=15;more=2;}else if c>=192{c&=31;more=1;}else{more=0;}for _ in 0..more{c=(c<<6)|(v[i]as u32&63);i+=1;}sum=sum.wrapping_add(c as u64);}}},
"allocate"=>{let mut v:Vec<Box<[u64;8]>>=Vec::with_capacity(n);for r in 0..rounds{let mut x=seed.wrapping_add(r as u32);for _ in 0..n{let mut b=Box::new([0u64;8]);b[0]=next(&mut x)as u64;b[7]=next(&mut x)as u64;v.push(b);}for b in &v{sum=sum.wrapping_add(b[0]+b[7]);}v.clear();}},_=>panic!("mode")};println!("{}",sum);}
'''
GO = r'''
package main
import("fmt";"os";"strconv";"slices")
func next(x *uint32)uint32{*x=*x*1664525+1013904223;return *x}
func main(){mode:=os.Args[1];n,_:=strconv.Atoi(os.Args[2]);rounds,_:=strconv.Atoi(os.Args[3]);s,_:=strconv.ParseUint(os.Args[4],10,32);seed:=uint32(s);var sum uint64
switch mode{
case "sort":v:=make([]uint32,n);for r:=0;r<rounds;r++{x:=seed+uint32(r);for i:=range v{v[i]=next(&x)};slices.Sort(v);for i,y:=range v{sum+=uint64(y)*uint64(i+1)}}
case "map":cap:=1;for cap<n*2{cap*=2};k:=make([]uint32,cap);v:=make([]uint32,cap);input:=make([]uint32,n);for r:=0;r<rounds;r++{clear(k);clear(v);x:=seed+uint32(r);for i:=range input{key:=1+(next(&x)>>8)%uint32(n*8);input[i]=key;p:=int(key*2654435761)&(cap-1);for k[p]!=0&&k[p]!=key{p=(p+1)&(cap-1)};k[p]=key;v[p]++};for p:=range k{sum+=uint64(k[p])*uint64(v[p])};for _,key:=range input{p:=int(key*2654435761)&(cap-1);for k[p]!=key{p=(p+1)&(cap-1)};sum+=uint64(key)*uint64(v[p])}}
case "utf8":v:=make([]byte,0,n*4);x:=seed;for j:=0;j<n;j++{c:=next(&x)%0x10f800;if c>=0xd800{c+=0x800};if c<128{v=append(v,byte(c))}else if c<2048{v=append(v,byte(192|(c>>6)),byte(128|(c&63)))}else if c<65536{v=append(v,byte(224|(c>>12)),byte(128|((c>>6)&63)),byte(128|(c&63)))}else{v=append(v,byte(240|(c>>18)),byte(128|((c>>12)&63)),byte(128|((c>>6)&63)),byte(128|(c&63)))}};for r:=0;r<rounds;r++{i:=0;for i<len(v){c:=uint32(v[i]);i++;more:=0;if c>=240{c&=7;more=3}else if c>=224{c&=15;more=2}else if c>=192{c&=31;more=1};for j:=0;j<more;j++{c=(c<<6)|uint32(v[i]&63);i++};sum+=uint64(c)}}
case "allocate":v:=make([][]uint64,n);for r:=0;r<rounds;r++{x:=seed+uint32(r);for i:=range v{v[i]=make([]uint64,8);v[i][0]=uint64(next(&x));v[i][7]=uint64(next(&x))};for _,b:=range v{sum+=b[0]+b[7]}}
default:panic("mode")};fmt.Println(sum)}
'''
DYN = r'''
use "std/io"
use "std/mem" mem
use "std/process"
use "std/sort"
use "std/bytes"
fn number(s:[]const u8) usize {v:usize=0;for b in s {v=v*10+#cast(usize,b-48)};return v}
fn next(x:*u32) u32 {x.*=#wrap(x.* * 1664525 + 1013904223);return x.*}
fn main(){arena:=mem.arena_create(268435456);defer mem.arena_release(&arena);args:=process.arguments(&arena);if !args.ok {#panic("args")};mode:=args.value[1];n:=number(args.value[2]);rounds:=number(args.value[3]);seed:=#cast(u32,number(args.value[4]));sum:u64=0
if bytes.equal(mode,"sort") {v:=mem.push_array(u32,&arena,n);for r in 0..rounds {x:=#wrap(seed+#cast(u32,r));for i in 0..n {v[i]=next(&x)};sort.sort(v);for i in 0..n {sum=#wrap(sum+#cast(u64,v[i])*#cast(u64,i+1))}}}
else if bytes.equal(mode,"map") {capacity:usize=1;for capacity<n*2 {capacity*=2};k:=mem.push_array(u32,&arena,capacity);v:=mem.push_array(u32,&arena,capacity);input:=mem.push_array(u32,&arena,n);for r in 0..rounds {for i in 0..capacity{k[i]=0;v[i]=0};x:=#wrap(seed+#cast(u32,r));for i in 0..n {key:=1+(next(&x)>>8)%#cast(u32,n*8);input[i]=key;p:=#cast(usize,#wrap(key*2654435761))&(capacity-1);for k[p]!=0 && k[p]!=key {p=(p+1)&(capacity-1)};k[p]=key;v[p]+=1};for p in 0..capacity {sum=#wrap(sum+#cast(u64,k[p])*#cast(u64,v[p]))};for key in input {p:=#cast(usize,#wrap(key*2654435761))&(capacity-1);for k[p]!=key {p=(p+1)&(capacity-1)};sum=#wrap(sum+#cast(u64,key)*#cast(u64,v[p]))}}}
else if bytes.equal(mode,"utf8") {v:=mem.push_array(u8,&arena,n*4);used:usize=0;x:=seed;for j in 0..n {c:=next(&x)%1112064;if c>=55296 {c+=2048};if c<128 {v[used]=#cast(u8,c);used+=1}else if c<2048 {v[used]=#cast(u8,192|(c>>6));v[used+1]=#cast(u8,128|(c&63));used+=2}else if c<65536 {v[used]=#cast(u8,224|(c>>12));v[used+1]=#cast(u8,128|((c>>6)&63));v[used+2]=#cast(u8,128|(c&63));used+=3}else {v[used]=#cast(u8,240|(c>>18));v[used+1]=#cast(u8,128|((c>>12)&63));v[used+2]=#cast(u8,128|((c>>6)&63));v[used+3]=#cast(u8,128|(c&63));used+=4}};for r in 0..rounds {i:usize=0;for i<used {c:=#cast(u32,v[i]);i+=1;more:usize=0;if c>=240 {c&=7;more=3}else if c>=224 {c&=15;more=2}else if c>=192 {c&=31;more=1};for j in 0..more {c=(c<<6)|#cast(u32,v[i]&63);i+=1};sum=#wrap(sum+#cast(u64,c))}}}
else if bytes.equal(mode,"allocate") {blocks:=mem.push_array([]u64,&arena,n);mark:=mem.arena_mark(&arena);for r in 0..rounds {x:=#wrap(seed+#cast(u32,r));for i in 0..n {blocks[i]=mem.push_array(u64,&arena,8);blocks[i][0]=#cast(u64,next(&x));blocks[i][7]=#cast(u64,next(&x))};for b in blocks {sum=#wrap(sum+b[0]+b[7])};mem.arena_rewind(&arena,mark)}}else {#panic("mode")};_=io.println(io.stdout(),"{}",sum)}
'''


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(command, timeout=120, env=None):
    result = subprocess.run([str(x) for x in command], capture_output=True,
                            text=True, timeout=timeout, env=env)
    if result.returncode:
        raise RuntimeError(f'{command!r}: exit {result.returncode}\n{result.stdout}\n{result.stderr}')
    return result


def oracle(kind, n, rounds, seed):
    total = 0
    for r in range(rounds if kind != 'utf8' else 1):
        x = (seed+r) & 0xffffffff
        values = []
        for _ in range(n*(2 if kind == 'allocate' else 1)):
            x = (x*1664525+1013904223) & 0xffffffff
            values.append(x)
        if kind == 'sort':
            total += sum((i+1)*v for i, v in enumerate(sorted(values)))
        elif kind == 'map':
            # Independent bag identity; lookup counts must actually be consumed.
            from collections import Counter
            counts = Counter(1+(v >> 8) % (n*8) for v in values)
            total += sum(key*(count+count*count) for key, count in counts.items())
        elif kind == 'allocate':
            total += sum(values)
        else:
            text = ''.join(chr(v % 0x10f800 + (0x800 if v % 0x10f800 >= 0xd800 else 0)) for v in values)
            assert text.encode('utf-8').decode('utf-8') == text
            total = sum(map(ord, text))*rounds
    return str(total & MASK)+'\n'


def prepare(args):
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sizes = {'sort': (128, 2), 'map': (256, 2), 'utf8': (256, 3), 'allocate': (128, 2)} if args.small else {
        'sort': (32768, 8), 'map': (65536, 8), 'utf8': (262144, 16), 'allocate': (8192, 32)}
    sources = {'dyn': ('main.dyn', DYN), 'c': ('main.c', C), 'rust': ('main.rs', RUST), 'go': ('main.go', GO)}
    tools = {'dyn': args.dyn.resolve(), 'c': shutil.which(args.cc), 'rust': shutil.which(args.rustc), 'go': shutil.which(args.go)}
    if any(not x or not Path(x).exists() for x in tools.values()):
        raise SystemExit('missing compiler: '+repr(tools))
    commands = {
        'dyn': [tools['dyn'], 'build', out/'dyn', '--release', '--opt-level', '3', '--no-cache', '--quiet', '--output', out/'dyn-bin'],
        'c': [tools['c'], '-O3', '-std=c11', out/'c/main.c', '-o', out/'c-bin'],
        'rust': [tools['rust'], '-C', 'opt-level=3', out/'rust/main.rs', '-o', out/'rust-bin'],
        'go': [tools['go'], 'build', '-o', out/'go-bin', out/'go/main.go'],
    }
    manifest = {'schema': 1, 'scope': SCOPES, 'host': platform.platform(), 'machine': platform.machine(),
                'timing_scope': 'whole process, including startup, input generation and shutdown; no CPU pinning by default',
                'small': args.small, 'seed': args.seed, 'languages': {}, 'cases': {},
                'dyn_sdk_source_sha256': hashlib.sha256(json.dumps(
                    {str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT/'std').rglob('*.dyn'))},
                    sort_keys=True).encode()).hexdigest(), 'limitations': [
                    'native host only; no general language ranking', 'sort and allocation algorithms/libraries differ',
                    'valid UTF-8 only; uniformly generated Unicode is mostly four-byte sequences; explicit decoder omits validation for all languages',
                    'allocation uses native zero initialization and different release/GC policies',
                    'runtime seed and size opaque to each compiler; no external input I/O timed',
                    'no memory/RSS measurement; operating-system scheduling and startup may dominate short cases']}
    env = dict(os.environ, DYN_SDK=str(ROOT))
    env.pop('DYN_NO_SSA', None)
    for lang, (filename, source) in sources.items():
        directory = out/lang
        directory.mkdir()
        path = directory/filename
        path.write_text(source.replace(';', '\n') if lang == 'dyn' else source)
        result = run(commands[lang], env=env)
        (out/(lang+'-build.log')).write_text(result.stdout+result.stderr)
        version = run([tools[lang], 'version' if lang == 'go' else '--version']).stdout.strip()
        actual_tool = Path(tools[lang]).resolve()
        if lang == 'rust' and shutil.which('rustup'):
            actual_tool = Path(run(['rustup', 'which', 'rustc']).stdout.strip()).resolve()
        if lang == 'go':
            candidate = Path(run([tools[lang], 'env', 'GOROOT']).stdout.strip())/'bin/go'
            if candidate.is_file():
                actual_tool = candidate.resolve()
        binary = out/(lang+'-bin')
        manifest['languages'][lang] = {'compiler': str(tools[lang]), 'version': version,
            'invoked_tool_sha256': digest(Path(tools[lang]).resolve()),
            'actual_compiler': str(actual_tool), 'compiler_sha256': digest(actual_tool), 'source': str(path.relative_to(out)),
            'source_sha256': digest(path), 'binary': binary.name, 'binary_sha256': digest(binary),
            'bytes': binary.stat().st_size, 'build_command': list(map(str, commands[lang]))}
    for kind, (n, rounds) in sizes.items():
        expected = oracle(kind, n, rounds, args.seed)
        case = {'n': n, 'rounds': rounds, 'seed': args.seed, 'expected': expected}
        for lang in sources:
            actual = run([out/(lang+'-bin'), kind, n, rounds, args.seed], timeout=30)
            if actual.stdout != expected or actual.stderr:
                raise RuntimeError((lang, kind, actual.stdout, actual.stderr, expected))
        manifest['cases'][kind] = case
        print('PASS correctness:', kind, repr(expected), flush=True)
    (out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    shutil.copy2(__file__, out/'extended.py')


def measure(args):
    out = args.output.resolve()
    manifest = json.loads((out/'manifest.json').read_text())
    report = {'schema': 1, 'manifest_sha256': digest(out/'manifest.json'), 'host': platform.platform(),
              'affinity': sorted(os.sched_getaffinity(0)) if hasattr(os, 'sched_getaffinity') else None,
              'warmups': args.warmups, 'samples': args.samples, 'results': {}, 'order': []}
    languages = list(manifest['languages'])
    for lang, entry in manifest['languages'].items():
        if digest(out/entry['binary']) != entry['binary_sha256'] or digest(out/entry['source']) != entry['source_sha256']:
            raise RuntimeError('artifact changed: '+lang)
    destination = out/args.result
    if destination.exists():
        raise SystemExit('refusing to overwrite '+str(destination))
    for kind, case in manifest['cases'].items():
        samples = {lang: [] for lang in languages}
        for iteration in range(args.warmups+args.samples):
            order = languages[iteration % len(languages):]+languages[:iteration % len(languages)]
            if iteration % 2:
                order = order[::-1]
            report['order'].append([kind, iteration, order])
            for lang in order:
                start = time.perf_counter_ns()
                actual = run([out/manifest['languages'][lang]['binary'], kind, case['n'], case['rounds'], case['seed']], timeout=30)
                elapsed = (time.perf_counter_ns()-start)/1e6
                if actual.stdout != case['expected'] or actual.stderr:
                    raise RuntimeError((lang, kind, actual.stdout, actual.stderr))
                if iteration >= args.warmups:
                    samples[lang].append(elapsed)
        report['results'][kind] = {lang: {'milliseconds': values, 'median_ms': statistics.median(values)} for lang, values in samples.items()}
        print(kind, {lang: round(v['median_ms'], 3) for lang, v in report['results'][kind].items()}, flush=True)
        destination.write_text(json.dumps(report, indent=2)+'\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--prepare-only', action='store_true')
    mode.add_argument('--measure-only', action='store_true')
    parser.add_argument('--small', action='store_true', help='small correctness workloads')
    parser.add_argument('--dyn', type=Path, default=ROOT/'build/dyn-release')
    parser.add_argument('--cc', default='cc')
    parser.add_argument('--rustc', default='rustc')
    parser.add_argument('--go', default='go')
    parser.add_argument('--seed', type=int, default=912345)
    parser.add_argument('--warmups', type=int, default=2)
    parser.add_argument('--samples', type=int, default=15)
    parser.add_argument('--result', default='results.json')
    args = parser.parse_args()
    if not 0 <= args.seed < 2**32 or args.samples < 1 or args.warmups < 0:
        parser.error('seed must be u32; samples positive; warmups nonnegative')
    if Path(args.result).name != args.result:
        parser.error('result must be a filename')
    prepare(args) if args.prepare_only else measure(args)

if __name__ == '__main__':
    main()
