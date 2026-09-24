#!/usr/bin/env python3
"""Deterministic lifecycle tests plus real SDL dummy-audio drain; GPU is opt-in."""
import argparse
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile
ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--gpu', action='store_true', help='Require three real GPU submissions with the selected SDL video driver')
args = parser.parse_args()
dyn = str(Path(os.environ.get('DYN', ROOT/'build/dyn-release')).resolve())
report = {'status':'running','gpu':'not-requested','audio':'pending','scope':'Mock lifecycle and real dummy audio do not establish hardware rendering or audible playback'}
work = ROOT/'build/readiness'; work.mkdir(parents=True, exist_ok=True)
def run(command, **kwargs):
    return subprocess.run(command,cwd=ROOT,check=True,timeout=30,**kwargs)
try:
    run(['python3','tests/sdl3-loop.py'],env=dict(os.environ,DYN=dyn))
    with tempfile.TemporaryDirectory(prefix='dyn-sdl-apps-') as directory:
        temp = Path(directory)
        mock = temp/'audio.so'
        flags = shlex.split(subprocess.check_output(['pkg-config','--cflags','sdl3'],text=True))
        run([*shlex.split(os.environ.get('CC','cc')),'-shared','-fPIC',*flags,'tests/sdl3-audio/mock.c','-o',str(mock)])
        for mode in ([],['--release']):
            binary = temp/'audio'
            run([dyn,'build','projects/sdl3-audio-example','--quiet','--no-cache','--output',str(binary),*mode])
            result = run([str(binary)],env=dict(os.environ,LD_PRELOAD=str(mock)),capture_output=True,text=True)
            assert 'PASS audio lifetime' in result.stdout, result
            for variable, expected in [('DYN_TEST_AUDIO_ERROR','SDL3 audio status failed'),('DYN_TEST_AUDIO_STALL','SDL3 audio drain timed out')]:
                failed = subprocess.run([str(binary)],env=dict(os.environ,LD_PRELOAD=str(mock),**{variable:'1'}),capture_output=True,text=True,timeout=8)
                assert failed.returncode != 0 and expected in failed.stderr, failed
            real = run([str(binary)],env=dict(os.environ,SDL_AUDIODRIVER='dummy'),capture_output=True,text=True)
            assert 'SDL3 audio drained' in real.stdout, real
            if args.gpu:
                gpu = temp/'gpu'
                run([dyn,'build','projects/sdl3-gpu-example','--quiet','--no-cache','--output',str(gpu),*mode])
                run([str(gpu),'--smoke'])
        report.update(status='passed', audio='mock failure/drain and native dummy debug/release',gpu='three submissions debug/release' if args.gpu else 'not-requested')
except BaseException as error:
    report.update(status='failed',error=str(error)); raise
finally:
    (work/'sdl-applications.json').write_text(json.dumps(report,indent=2)+'\n')
print('PASS SDL application lifecycle; hardware playback remains separate')
