#!/usr/bin/env python3
"""Docs SDK lookup from arbitrary cwd, overrides, local precedence and file scope."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
DYN=str(Path(os.environ.get('DYN',ROOT/'build/dyn-release')).resolve())

def run(arguments,cwd,env):
    return subprocess.run([DYN,*arguments],cwd=cwd,env=env,capture_output=True,text=True,timeout=30)

def declarations(result):
    assert result.returncode==0,result.stderr
    report=json.loads(result.stdout)
    assert report['analysis']=='syntax-only' and report['target_selection']=='all-source-files'
    return {d['name'] for f in report['files'] for d in f['declarations']}

with tempfile.TemporaryDirectory(prefix='dyn-sdk-docs-') as temporary:
    root=Path(temporary);cwd=root/'project';cwd.mkdir()
    env=dict(os.environ);env.pop('DYN_SDK',None)
    assert 'arena_create' in declarations(run(['docs','std/mem','--json'],cwd,env))
    assert 'prepare' in declarations(run(['docs','vendor/sqlite','--json'],cwd,env))
    result=run(['docs','std/mem'],cwd,env)
    assert result.returncode==0 and 'arena_create' in result.stdout,result.stderr
    sdk=root/'custom sdk'; standard=sdk/'std/example';vendor=sdk/'vendor/example'
    standard.mkdir(parents=True);vendor.mkdir(parents=True)
    original='pub fn Standard( ) u64{return 1}\n'
    (standard/'main.dyn').write_text(original)
    (standard/'other.dyn').write_text('#target(kernel: windows)\npub const Other: usize = 2\n')
    (vendor/'main.dyn').write_text('pub const Vendor: usize = 3\n')
    env['DYN_SDK']=str(sdk)
    # SDK declaration lookup is independent of a broken project manifest.
    (cwd/'dyn.project').write_text('this is not a valid manifest\n')
    assert declarations(run(['docs','std/example','--json'],cwd,env))=={'Standard','Other'}
    assert declarations(run(['docs','std/example/main.dyn','--json'],cwd,env))=={'Standard'}
    assert declarations(run(['docs','vendor/example','--json'],cwd,env))=={'Vendor'}
    result=run(['fmt','std/example'],cwd,env)
    assert result.returncode==2 and not result.stdout,result
    assert (standard/'main.dyn').read_text()==original,'formatter must not fall back to SDK paths'
    local=cwd/'std/example';local.mkdir(parents=True)
    (local/'main.dyn').write_text('pub const Local: usize = 4\n')
    assert declarations(run(['docs','std/example','--json'],cwd,env))=={'Local'}
    assert declarations(run(['docs','./std/example','--json'],cwd,env))=={'Local'}
    assert declarations(run(['docs','std/example/main.dyn','--json'],cwd,env))=={'Local'}
    assert declarations(run(['docs',str(standard),'--json'],cwd,env))=={'Standard','Other'}
    for path in ['std/not-a-real-module','vendor/not-a-real-module']:
        result=run(['docs',path,'--json'],cwd,env)
        assert result.returncode!=0 and not result.stdout,result
    broken=sdk/'std/broken';broken.mkdir()
    (broken/'a.dyn').write_text('pub const Visible: usize = 1\n')
    (broken/'b.dyn').write_text('pub fn broken( {\n')
    result=run(['docs','std/broken','--json'],cwd,env)
    assert result.returncode!=0 and not result.stdout,result
print('PASS docs SDK paths: arbitrary cwd, DYN_SDK, vendor paths, local precedence, single-file scope, atomic errors; formatter unchanged')
