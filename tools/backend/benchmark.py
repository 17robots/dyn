#!/usr/bin/env python3
"""Matched prepared-IR emission benchmark; no whole-compiler speed claim."""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
BUILD = Path(os.environ.get('BUILD', ROOT/'build')).resolve()
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--sizes', nargs='+', type=int, default=[64, 256, 1024])
parser.add_argument('--runs', type=int, default=5)
parser.add_argument('--calls', type=int, default=5000000)
parser.add_argument('--output', type=Path, default=BUILD/'backend-benchmark.json')
args = parser.parse_args()
if args.runs < 1 or args.calls < 1 or any(n < 1 or n > 2048 for n in args.sizes):
    parser.error('positive runs/calls and sizes in 1..2048 required')
if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
    parser.error('benchmark requires x86-64 Linux')
cc = shlex.split(os.environ.get('CC', 'cc'))
work = BUILD/'backend-benchmark-work'
work.mkdir(parents=True, exist_ok=True)
exe = BUILD/'backend-benchmark'

def run(command):
    result = subprocess.run([str(x) for x in command], check=False, capture_output=True, text=True, timeout=180)
    if result.returncode or result.stderr:
        raise RuntimeError(f"{command}: exit {result.returncode}\n{result.stdout}{result.stderr}")
    return result.stdout

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

# Refresh explicit artifacts before timing; build signatures capture the commands.
build_command = [sys.executable, ROOT/'tools/build.py', 'backend-benchmark',
                 'dynrt_shared.o', 'dynrt_support_pic.o']
run(build_command)
build_records = {}
def record_build(path):
    stamp = Path(str(path)+'.build.json')
    if not stamp.exists() or str(stamp) in build_records:
        return
    record = json.loads(stamp.read_text())
    build_records[str(stamp)] = record
    for dependency in record['inputs']:
        record_build(Path(dependency))
for artifact in (exe, BUILD/'dynrt_shared.o', BUILD/'dynrt_support_pic.o'):
    record_build(artifact)

runner_source = work/'runner.c'
runner_source.write_text(r'''#define _POSIX_C_SOURCE 200809L
#include <dlfcn.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
int main(int argc,char **argv) {
  if(argc!=3)return 2;
  void *lib=dlopen(argv[1],RTLD_NOW);
  if(!lib)return 2;
  uint64_t (*f)(uint64_t,uint64_t) = (uint64_t (*)(uint64_t,uint64_t))dlsym(lib,"bench_f0");
  if(!f)return 2;
  uint64_t n=strtoull(argv[2],NULL,10), x=17;
  struct timespec a,b; clock_gettime(CLOCK_MONOTONIC,&a);
  for(uint64_t i=0;i<n;++i)x=f(x,i);
  clock_gettime(CLOCK_MONOTONIC,&b);
  printf("{\"checksum\":\"%" PRIu64 "\",\"seconds\":%.9f}\n",x,
    (double)(b.tv_sec-a.tv_sec)+(double)(b.tv_nsec-a.tv_nsec)/1e9);
  dlclose(lib); return 0;
}
''')
runner = work/'runner'
runner_command = [*cc, '-std=c11', '-O2', runner_source, '-ldl', '-o', runner]
run(runner_command)
report = {
    'scope': 'Fresh process per sample, identical prepared IR and harness. Emission includes target initialization and object I/O; excludes parsing, IR preparation, linking and process startup. Debug enables runtime tracing but disables DWARF in both emitters. Release LLVM uses its normal optimization policy. RSS is whole matched harness including preparation and shared LLVM linkage, not standalone emitter memory.',
    'host': platform.platform(), 'machine': platform.machine(),
    'current_environment_compiler': run([*cc, '--version']).splitlines()[0],
    'current_environment_llvm': run(shlex.split(os.environ.get('LLVM_CONFIG', 'llvm-config'))+['--version']).strip(),
    'invocation': [sys.executable, *sys.argv],
    'build_command': list(map(str, build_command)), 'build_records': build_records,
    'runner_compile_command': list(map(str, runner_command)),
    'runtime_sha256': {name:sha(BUILD/name) for name in ('dynrt_shared.o','dynrt_support_pic.o')},
    'harness_sha256': sha(exe), 'runner_sha256': sha(runner_source),
    'implementation_sha256': {str(p.relative_to(ROOT)): sha(p) for p in [
        ROOT/'src/backend/driver.c', ROOT/'src/backend/benchmark-driver.c',
        Path(__file__).resolve(), ROOT/'src/codegen.c', ROOT/'src/ir.c', ROOT/'src/dyn_location.h']},
    'runs': args.runs, 'runtime_calls': args.calls, 'rows': [],
}
for size in args.sizes:
    source = work/f'functions-{size}.dyn'
    source.write_text('pub fn bench_leaf(a:u64,b:u64) u64 {return #wrap(a*131+b)}\n'+''.join(
        f'pub fn bench_f{i}(a:u64,b:u64) u64 {{if a<b {{return #wrap(bench_leaf(a,b)+{i})}} return bench_leaf(b,a)^{i}}}\n'
        for i in range(size)))
    for mode in ('debug', 'release'):
        samples = {'scalar': [], 'llvm': []}
        commands = {}
        libraries = {}
        for iteration in range(args.runs):
            for backend in (('scalar', 'llvm') if iteration % 2 == 0 else ('llvm', 'scalar')):
                obj = work/f'{size}-{mode}-{backend}.o'
                command = [exe, backend, mode, source, obj]
                start = time.perf_counter()
                result = json.loads(run(command))
                result['process_seconds'] = time.perf_counter()-start
                result['object_bytes'] = obj.stat().st_size
                samples[backend].append(result)
                commands[backend] = list(map(str, command))
        for backend in samples:
            obj = work/f'{size}-{mode}-{backend}.o'
            library = work/f'{size}-{mode}-{backend}.so'
            command = [*cc, '-shared', '-Wl,--no-undefined', obj,
                       BUILD/'dynrt_shared.o', BUILD/'dynrt_support_pic.o', '-o', library]
            run(command)
            commands[backend+'_link'] = list(map(str, command))
            libraries[backend] = library
        # Execution is outside emission timing. Validate every generated function.
        loaded = {key: ctypes.CDLL(str(path)) for key, path in libraries.items()}
        mask = (1 << 64)-1
        for i in range(size):
            functions = [getattr(lib, f'bench_f{i}') for lib in loaded.values()]
            for f in functions:
                f.argtypes = [ctypes.c_uint64, ctypes.c_uint64]; f.restype = ctypes.c_uint64
            for a,b in ((0,1),(1,0),(mask,1),(1,mask),(mask,mask)):
                expected = ((a*131+b+i) if a<b else ((b*131+a)&mask)^i)&mask
                assert all(f(a,b)==expected for f in functions), (size,mode,i,a,b)
        runtime = {'scalar': [], 'llvm': []}
        checksum = None
        for iteration in range(args.runs):
            for backend in (('scalar','llvm') if iteration % 2 == 0 else ('llvm','scalar')):
                command = [runner, libraries[backend], str(args.calls)]
                result = json.loads(run(command))
                if checksum is None: checksum = result['checksum']
                assert checksum == result['checksum'], (mode, size, backend, result)
                runtime[backend].append(result['seconds'])
                commands[backend+'_runtime'] = list(map(str, command))
        medians = {key: {metric: statistics.median(sample[metric] for sample in values)
                         for metric in values[0]} for key, values in samples.items()}
        row = {'functions': size+1, 'mode': mode, 'source_sha256': sha(source),
               'source_bytes': source.stat().st_size, 'commands': commands, 'samples': samples,
               'medians': medians, 'runtime_samples_seconds': runtime,
               'runtime_medians_seconds': {key:statistics.median(values) for key,values in runtime.items()},
               'runtime_checksum': checksum, 'value_comparisons':size*5}
        report['rows'].append(row)
        print(f'{size+1} functions {mode}: scalar emit {medians["scalar"]["emit_seconds"]:.6f}s; LLVM {medians["llvm"]["emit_seconds"]:.6f}s', flush=True)
args.output.parent.mkdir(parents=True, exist_ok=True)
args.output.write_text(json.dumps(report, indent=2)+'\n')
print(args.output)
