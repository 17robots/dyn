#!/usr/bin/env python3
"""Repeat a command, retaining raw samples and per-child resource use as JSON.

Example: python3 tools/benchmark.py --output build/runtime.json -- build/program
For cold builds put both --artifact and DYN_CACHE_DIR under --reset-dir. This
removes only a directory created/marked by this tool; it never flushes OS caches.
RSS is the OS wait4 maximum, NOT aggregate simultaneous process-tree memory.
"""
import argparse, hashlib, json, math, os, platform, shutil, signal, statistics, subprocess, tempfile, time
from pathlib import Path

def measure(command, env, timeout):
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        start=time.monotonic()
        child=subprocess.Popen(command,env=env,stdout=stdout,stderr=stderr,start_new_session=os.name!='nt')
        usage=None
        if hasattr(os,'wait4'):
            while True:
                pid,status,resource=os.wait4(child.pid,os.WNOHANG)
                if pid:
                    child.returncode=os.waitstatus_to_exitcode(status); usage=resource; break
                if time.monotonic()-start > timeout:
                    os.killpg(child.pid,signal.SIGKILL); os.waitpid(child.pid,0); child.returncode=-9
                    raise TimeoutError(f'benchmark command exceeded {timeout}s')
                time.sleep(.001)
        else:
            try: child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                child.kill(); child.wait(); raise
        seconds=time.monotonic()-start
        stdout.seek(0); stderr.seek(0)
        out=stdout.read(); err=stderr.read()
        if child.returncode:
            raise RuntimeError(f'command failed ({child.returncode}): {err.decode(errors="replace")}')
        rss=usage.ru_maxrss if usage else None
        if rss is not None and platform.system()!='Darwin': rss*=1024
        return dict(seconds=seconds,max_rss_bytes=rss,
                    user_seconds=usage.ru_utime if usage else None,
                    system_seconds=usage.ru_stime if usage else None,
                    stdout_sha256=hashlib.sha256(out).hexdigest(),
                    stdout=out.decode(errors='replace'),stderr=err.decode(errors='replace'))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples',type=int,default=7)
    parser.add_argument('--warmup',type=int,default=1)
    parser.add_argument('--timeout',type=float,default=120)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--artifact',type=Path)
    parser.add_argument('--reset-dir',type=Path)
    parser.add_argument('--require-stable-output',action='store_true')
    parser.add_argument('command',nargs=argparse.REMAINDER)
    args=parser.parse_args(); command=args.command
    if command[:1]==['--']: command=command[1:]
    if not command or args.samples<1 or args.warmup<0 or args.timeout<=0: parser.error('invalid command/sample count/timeout')
    reset=args.reset_dir.resolve() if args.reset_dir else None
    marker='.dyn-benchmark-owned'
    if reset:
        if not args.artifact or reset not in args.artifact.resolve().parents:
            parser.error('cold builds require --artifact inside --reset-dir, so executable caches are reset too')
        if reset.exists() and not (reset/marker).is_file():
            parser.error('reset directory exists without benchmark ownership marker; use a new dedicated path')
        if reset in [Path.cwd(),args.output.resolve().parent] or reset in args.output.resolve().parents:
            parser.error('output must be outside reset directory')
        reset.mkdir(parents=True,exist_ok=True); (reset/marker).touch()
    rows=[]
    for index in range(args.warmup+args.samples):
        if reset:
            shutil.rmtree(reset); reset.mkdir(); (reset/marker).touch()
        row=measure(command,dict(os.environ),args.timeout)
        if index>=args.warmup: rows.append(row)
    if args.require_stable_output and len({r['stdout_sha256'] for r in rows})!=1:
        raise RuntimeError('benchmark output changed across samples')
    times=sorted(r['seconds'] for r in rows)
    report=dict(command=command,platform=platform.platform(),samples=rows,
                cache='dedicated directory reset; OS cache retained' if reset else 'caller-controlled',
                rss_definition='wait4 maximum; not concurrent aggregate; null where unavailable',
                artifact_bytes=args.artifact.stat().st_size if args.artifact else None,
                artifact_sha256=hashlib.sha256(args.artifact.read_bytes()).hexdigest() if args.artifact else None,
                summary=dict(minimum_seconds=times[0],median_seconds=statistics.median(times),
                             p90_seconds=times[math.ceil(.9*len(times))-1],maximum_seconds=times[-1]))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report['summary']))
if __name__=='__main__': main()
